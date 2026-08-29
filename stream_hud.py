"""
stream_hud.py

The video-streaming layer that sits OUTSIDE hud_reader.py's boundary and
feeds it frames one at a time. hud_reader stays ignorant of video files,
live streams, and timing -- all of that lives here.

Emits one parsed reading per sampled frame as JSONL (one JSON object per
line), to stdout and optionally to a file. Each line looks like:

    {"t": 1.5, "readings": {"speed": 28.5, "power": [74, "W"], "rpm": 36}}

("unit_value" fields become [number, unit] arrays in JSON.)

Two concerns are kept independent (see CLAUDE.md "Next step"):

  * SOURCE  -- where frames come from. Only a video FILE is implemented
              here; a live source would slot in as another frame
              generator without any consumer needing to change.
  * PACING  -- how fast output is emitted:
                - "fast"     : as fast as OCR allows (default; for testing)
                - "realtime" : paced to real elapsed time, so a 5-minute
                               clip takes 5 minutes -- this simulates the
                               live path.
              A file supports BOTH; a live source is inherently realtime.

The emitted output format is IDENTICAL across every mode -- only the delay
between lines differs -- so nothing downstream needs to know which mode
produced the stream.

Usage:
    # Fast (default): process a 5s range as quickly as OCR allows
    python stream_hud.py --video data/training/trimmed-video.mp4 --start-time 0 \
        --end-time 5 --fps 2

    # Realtime: same range, but paced so it takes ~5 real seconds
    python stream_hud.py --video data/training/trimmed-video.mp4 --start-time 0 \
        --end-time 5 --fps 2 --pace realtime

    # Also tee the JSONL stream to a file
    python stream_hud.py --video data/training/trimmed-video.mp4 --fps 1 --out run.jsonl
"""

import argparse
import json
import sys
import time
from typing import Iterator, Optional, Tuple

import cv2

import hud_reader

Frame = Tuple[float, "cv2.typing.MatLike"]  # (video_timestamp_sec, frame)


def iter_video_frames(
    video_path: str,
    start_time: float = 0.0,
    end_time: Optional[float] = None,
    sample_fps: float = 1.0,
) -> Iterator[Frame]:
    """Yield (video_timestamp_sec, frame) for sampled frames in [start, end).

    Sampling is by VIDEO timestamp (relative to start_time), so the exact
    same frames are selected regardless of how the output is later paced --
    that's what makes fast and realtime streams identical in content.

    No pacing / timing happens here: this is a pure frame source.
    """
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        sys.exit(f"Could not open video: {video_path}")

    try:
        native_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        if sample_fps <= 0:
            sys.exit(f"--fps must be positive, got {sample_fps}")

        # How many native frames to advance between emitted samples.
        step = max(1, round(native_fps / sample_fps))
        start_index = int(start_time * native_fps)
        end_index = int(end_time * native_fps) if end_time is not None else None

        cap.set(cv2.CAP_PROP_POS_FRAMES, start_index)

        index = start_index
        while True:
            if end_index is not None and index >= end_index:
                break
            ok, frame = cap.read()
            if not ok:
                break  # ran off the end of the video

            if (index - start_index) % step == 0:
                timestamp = index / native_fps - start_time
                yield (timestamp, frame)
            index += 1
    finally:
        cap.release()


def pace(frames: Iterator[Frame], mode: str) -> Iterator[Frame]:
    """Wrap a frame iterator, delaying each item according to `mode`.

    - "fast": pass frames through immediately, no delay.
    - "realtime": hold each frame until real elapsed time catches up to its
      video timestamp, so emission tracks the video clock. If OCR upstream
      already ate more wall-clock time than the frame's timestamp (we're
      behind), don't sleep -- yield immediately and record the drift so a
      silently-lagging stream is visible rather than hidden.

    Drift only exists in realtime mode; in fast mode it is meaningless.
    """
    if mode == "fast":
        yield from frames
        return

    if mode != "realtime":
        sys.exit(f"Unknown pace mode: {mode!r} (expected 'fast' or 'realtime')")

    start_wallclock = time.monotonic()
    worst_drift = 0.0
    drifted = False

    for timestamp, frame in frames:
        target = start_wallclock + timestamp
        now = time.monotonic()
        wait = target - now
        if wait > 0:
            time.sleep(wait)
        else:
            # We're behind the video clock -- emit now, but note how far.
            drifted = True
            worst_drift = max(worst_drift, -wait)
        yield (timestamp, frame)

    if drifted:
        print(
            f"[stream_hud] WARNING: realtime pacing fell behind by up to "
            f"{worst_drift:.2f}s -- OCR could not keep up with --fps at this "
            f"resolution. Output is complete but not perfectly paced.",
            file=sys.stderr,
        )


def stream(
    video_path: str,
    config: dict,
    start_time: float = 0.0,
    end_time: Optional[float] = None,
    sample_fps: float = 1.0,
    mode: str = "fast",
) -> Iterator[dict]:
    """Yield one parsed-reading record per sampled frame.

    Each record: {"t": <video_timestamp>, "readings": {name: value_or_None}}.
    This is the reusable core -- the CLI below just serializes it to JSONL.
    """
    frames = iter_video_frames(video_path, start_time, end_time, sample_fps)
    for timestamp, frame in pace(frames, mode):
        readings = hud_reader.extract_hud(frame, config)
        yield {"t": round(timestamp, 3), "readings": readings}


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--video", required=True, help="Path to the input video file")
    parser.add_argument("--config", default="configs/hud_config.json",
                        help="Path to a hud_reader-style config JSON (default: configs/hud_config.json)")
    parser.add_argument("--start-time", type=float, default=0.0,
                        help="Start of the time range to read, in seconds (default: 0)")
    parser.add_argument("--end-time", type=float, default=None,
                        help="End of the time range, in seconds (default: end of video)")
    parser.add_argument("--fps", type=float, default=1.0,
                        help="Sampling rate: readings emitted per second of video (default: 1)")
    parser.add_argument("--pace", choices=["fast", "realtime"], default="fast",
                        help="fast = as quick as OCR allows (default, for testing); "
                             "realtime = paced to real elapsed time (simulates live)")
    parser.add_argument("--out", default=None,
                        help="Optional path to also write the JSONL stream to")
    args = parser.parse_args()

    config = hud_reader.load_config(args.config)

    out_file = open(args.out, "w") if args.out else None
    try:
        for record in stream(args.video, config, args.start_time, args.end_time,
                             args.fps, args.pace):
            line = json.dumps(record)
            print(line, flush=True)
            if out_file is not None:
                out_file.write(line + "\n")
                out_file.flush()
    finally:
        if out_file is not None:
            out_file.close()


if __name__ == "__main__":
    main()
