"""
live_source.py -- live screen-capture SOURCE for the Rouvy OCR pipeline.

Mirrors the file-source contract documented in CLAUDE.md / stream_hud.py:
    iter_frames(video_path, start_time=0, end_time=None, sample_rate=1.0)
        -> yields (timestamp_sec, frame)

This module provides the live equivalent:
    iter_live_frames(region, duration=None, sample_rate=1.0)
        -> yields (timestamp_sec, frame)

Same yield shape (timestamp: float seconds since start, frame: BGR numpy
array) so it can be swapped in wherever stream_hud.py currently calls its
file-based iter_frames -- extract_hud(), pace_realtime(), etc. should not
need to know or care which source produced the frame.

ASSUMPTION (flag if wrong): your actual iter_frames signature differs from
the above -- e.g. different param names/order. If so, the fix is almost
certainly just renaming this function's params to match, not restructuring
anything, since the yield contract (timestamp, frame) is the only thing
that has to line up for run_stream()/pace_realtime() to accept either
source interchangeably.

Requires: mss, numpy, opencv-python (mss for capture, cv2 for the BGR
array shape hud_reader.py already expects -- same array type as
cv2.VideoCapture frames, no conversion needed downstream).

    pip install mss --break-system-packages
"""

import time

import numpy as np

try:
    import mss
except ImportError as e:
    raise ImportError(
        "live_source.py requires the 'mss' package: "
        "pip install mss --break-system-packages"
    ) from e


def find_rouvy_region():
    """
    One-off helper: prints all monitor geometries mss can see, so you can
    pick/verify the region for --region before your first live run.

    Doesn't guess which window is Rouvy -- window-title-based capture is a
    separate (more fragile, OS-specific) mechanism from region-based
    capture. For a first live test, it's simpler to just run Rouvy
    windowed/fullscreen on a known monitor and hardcode that monitor's
    box, which is what this function is for.
    """
    with mss.mss() as sct:
        for i, mon in enumerate(sct.monitors):
            print(f"monitor[{i}]: {mon}")


def iter_live_frames(region, duration=None, sample_fps=1.0):
    """
    Live equivalent of stream_hud.py's iter_video_frames().

    Args:
        region: dict with keys {"left", "top", "width", "height"} -- the
            screen rectangle to capture. Get this from find_rouvy_region()
            or trial-and-error with a quick screenshot. If Rouvy runs
            fullscreen on a single monitor, this can just be that
            monitor's full geometry.
        duration: seconds to run before stopping, or None to run until the
            caller breaks out of the loop (e.g. Ctrl+C, or an external
            stop condition). Mirrors iter_video_frames' start/end but as
            an elapsed-time window instead of in-video timestamps, since
            there's no "video" to seek into -- only "now" and "how long."
        sample_fps: frames per second to sample at -- named to match
            iter_video_frames' param exactly, but means something slightly
            different here: the file source skips frames that already
            exist in the video; this source ACTIVELY THROTTLES capture to
            roughly this rate, since unlike a file, there's no upper bound
            on how fast you could grab screenshots (limited only by
            mss/CPU), and OCR can't keep up with an unthrottled loop
            anyway (demo_v1.py's --ocr-every hold-last-good-reading
            pattern already tells you this -- expect a similar rate here
            as a starting point, e.g. 2-5 fps, and tune from your live
            results, not off this comment).

    Yields:
        (timestamp_sec, frame) -- timestamp is seconds elapsed since this
        generator started (matches iter_video_frames' "seconds into the
        clip" semantics, just measured against wall-clock start instead
        of video start). frame is a BGR numpy array, same shape/dtype as
        a cv2.VideoCapture frame, so extract_hud() needs zero changes.
    """
    interval = 1.0 / sample_fps
    start = time.monotonic()

    with mss.MSS() as sct:
        while True:
            now = time.monotonic()
            elapsed = now - start

            if duration is not None and elapsed >= duration:
                return

            shot = sct.grab(region)
            # mss gives BGRA; drop the alpha channel to match the BGR
            # shape cv2.VideoCapture/imread already produce -- this is
            # the one real format difference between this source and the
            # file source, kept isolated to this one line so nothing
            # downstream (hud_reader.py, extract_hud) needs to know
            # capture-vs-file frames ever differed.
            frame = np.array(shot)[:, :, :3]

            yield (elapsed, frame)

            # Throttle to sample_rate. This sleeps for whatever's left of
            # the interval after the grab+yield cost -- if processing
            # (OCR) is slower than `interval`, this sleep is skipped
            # entirely and frames arrive as fast as the caller consumes
            # them, same "best effort" behavior you'd want from a live
            # feed rather than blocking capture on a fixed clock.
            spent = time.monotonic() - now
            if spent < interval:
                time.sleep(interval - spent)


def snapshot(region, out_path="live_snapshot.png", delay=0):
    """
    One-shot sanity check: grab a single frame from `region` and save it
    to disk. Run this BEFORE stream_hud.py --live, especially when the
    "live" source is actually a video playing back on screen (e.g. no
    Rouvy access yet, testing against a screen-recorded mp4 instead) --
    it catches the two failure modes that would otherwise look like OCR
    bugs but aren't:
        1. Black/frozen frame -- usually means the player is using an
           exclusive/DirectX fullscreen mode that screen-capture APIs
           can't see through. Switch the player to windowed or
           borderless-fullscreen and retry.
        2. Wrong crop -- if the played-back video is scaled/letterboxed
           differently than the resolution your hud_config.json boxes
           were calibrated against, the region will look "right" at a
           glance but be reading the wrong pixels once boxes are applied.

    `delay`: seconds to count down before capturing. Screen capture grabs
    whatever is TOPMOST on screen at the instant it runs -- if you have
    to alt-tab to a terminal to type this command, the video player often
    drops out of fullscreen/loses topmost status the moment it loses
    focus, so a same-instant capture from a terminal actually captures
    the terminal/IDE, not the player, even though the player is the thing
    you meant to check. Set delay=5 (or more), hit enter, then immediately
    alt-tab back to the fullscreen player before time runs out.
    """
    if delay > 0:
        print(f"Capturing in {delay}s -- alt-tab to the target window now.")
        for remaining in range(int(delay), 0, -1):
            print(remaining, end=" ", flush=True)
            time.sleep(1)
        print()

    with mss.MSS() as sct:
        shot = sct.grab(region)
        frame = np.array(shot)[:, :, :3]
    import cv2
    cv2.imwrite(out_path, frame)
    print(f"Saved snapshot: {out_path} ({frame.shape[1]}x{frame.shape[0]}px)")
    print("Open it and confirm: not black, and the HUD looks like what "
          "your recorded-video crops expect (same scale/position).")


if __name__ == "__main__":
    # Quick manual check: run this file directly to confirm mss can see
    # your monitors before wiring anything else up.
    find_rouvy_region()