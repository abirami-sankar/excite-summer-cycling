"""
live_readout.py -- human-readable LIVE readout of the OCR reads.

Built for the check-in demo: play a recorded Rouvy ride as if it were a
live feed and print a clean, labeled, one-line-per-sample readout that
ticks in real time -- so an audience sees "the system is reading the real
ride" instead of a wall of raw JSONL. Low-confidence frames print "--"
(the reader never emits a guess it isn't sure of -- gaps, not wrong data).

Deliberately SELF-CONTAINED: it drives the video and OCR itself rather
than piping from stream_hud.py, because that file is currently a duplicate
of live_source.py (the real streaming CLI was clobbered -- restore it from
git before relying on it again). It still reuses the proven pure-OCR core
(hud_reader.load_config + extract_hud) unchanged, so what it prints is
exactly what the pipeline reads.

Usage (the campus demo):
    python live_readout.py --video data/training/RouvyCampusTest.mp4 \
        --config configs/campus_hud_config.json --start 360 --end 400 --fps 2

    # side-by-side idea: play the same clip in a media player next to
    # this terminal so the on-screen HUD lines up with the readout.

    # --pace fast   -> run as quick as OCR allows (for a dry run)
    # --pace realtime (default) -> tick at wall-clock speed, like a live feed
"""

import argparse
import time

import cv2

from hud_reader import load_config, extract_hud

# Fields to show, in column order: (config key, header label).
# Kept short and glanceable -- the four the demo talks to. Add more if the
# config has them and you want them on screen.
FIELD_LABELS = {
    "speed": "SPEED", "rpm": "CADENCE", "power": "POWER",
    "current_distance": "DISTANCE", "remaining_distance": "REMAIN",
    "current_elevation": "ELEV", "max_elevation": "MAXELEV",
}
DISPLAY = [(f, FIELD_LABELS[f]) for f in ("speed", "rpm", "power", "current_distance")]

COL_W = 13  # width of each value column


def _fmt(field, value):
    """Format one reading for display. None -> '--'. unit_value tuples show
    number + unit; power's unit is normalized to the constant 'W' (its OCR
    unit is cosmetic and unreliable -- see CLAUDE.md bug #4)."""
    if value is None:
        units = {"speed": "km/h", "rpm": "rpm", "power": "W"}
        return "-- " + units.get(field, "")
    if isinstance(value, tuple):  # unit_value: (number, unit)
        num, unit = value
        if field == "power":
            unit = "W"
        return f"{num} {unit}"
    if field == "speed":
        return f"{value} km/h"
    if field == "rpm":
        return f"{value} rpm"
    return f"{value}"


def _load_checked_config(config_path):
    config = load_config(config_path)
    for field, _ in DISPLAY:
        if field not in config:
            raise SystemExit(f"Field '{field}' not in {config_path} -- edit DISPLAY or the config.")
    return config


def _print_header(title):
    header = "  time   " + "".join(lbl.ljust(COL_W) for _, lbl in DISPLAY)
    print(f"\n{title}\n")
    print(header)
    print("  " + "-" * (len(header) - 2))


def _print_row(label, readings):
    print(f"  {label:<7}" + "".join(_fmt(f, readings.get(f)).ljust(COL_W) for f, _ in DISPLAY),
          flush=True)


def run(video, config_path, start, end, fps, pace):
    """Read from a recorded video file."""
    config = _load_checked_config(config_path)
    cap = cv2.VideoCapture(video)
    if not cap.isOpened():
        raise SystemExit(f"Could not open video: {video}")
    native_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0

    _print_header(f"Live OCR readout -- {video}  (t={start}..{end}s, {fps} samples/s)")
    interval = 1.0 / fps
    wall_start = time.monotonic()
    t = float(start)
    while t <= end:
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(t * native_fps))
        ok, frame = cap.read()
        if not ok:
            break
        readings = extract_hud(frame, config)
        _print_row(f"+{t - start:4.1f}s", readings)
        if pace == "realtime":
            slack = wall_start + (t - start) + interval - time.monotonic()
            if slack > 0:
                time.sleep(slack)
        t += interval
    cap.release()
    print("\n(done)\n")


def run_live(config_path, region, duration, fps, debug_save=None):
    """Read from a LIVE SCREEN CAPTURE of `region` -- proves the capture path
    works end to end (screen -> crop -> OCR -> readout). Reuses
    live_source.iter_live_frames, which throttles capture to `fps` in real
    time, so no --pace is needed here. Ctrl+C to stop if no --duration.

    `debug_save`: write the FIRST captured frame to this path, so you can
    confirm mss actually grabbed the ride (not a black/blanked screen or the
    terminal on top -- the bug-#5 failure mode). Diagnose staging with this
    before trusting an all-`--` run."""
    from live_source import iter_live_frames  # lazy: file mode shouldn't require mss
    config = _load_checked_config(config_path)
    dur = f", {duration}s" if duration else ", Ctrl+C to stop"
    _print_header(f"LIVE screen readout -- region {region}  ({fps} samples/s{dur})")
    saved = False
    for elapsed, frame in iter_live_frames(region, duration=duration, sample_fps=fps):
        if debug_save and not saved:
            cv2.imwrite(debug_save, frame)
            print(f"  [debug] first captured frame -> {debug_save} "
                  f"({frame.shape[1]}x{frame.shape[0]}); open it to see what mss actually grabbed")
            saved = True
        readings = extract_hud(frame, config)
        _print_row(f"+{elapsed:4.1f}s", readings)
    print("\n(done)\n")


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--video", default="data/training/RouvyCampusTest.mp4")
    p.add_argument("--config", default="configs/campus_hud_config.json")
    p.add_argument("--start", type=float, default=0.0, help="start time (s)")
    p.add_argument("--end", type=float, default=60.0, help="end time (s)")
    p.add_argument("--fps", type=float, default=2.0, help="samples per second to read/print")
    p.add_argument("--pace", choices=["realtime", "fast"], default="realtime",
                   help="realtime = tick at wall-clock speed (live feel); fast = as quick as OCR allows")
    p.add_argument("--live", action="store_true",
                   help="capture the SCREEN instead of a video file (proves screen capture works)")
    p.add_argument("--region", default=None,
                   help="live mode: left,top,width,height of the screen area to capture "
                        "(e.g. 0,0,1920,1080 for a full 1080p monitor; see live_source.find_rouvy_region)")
    p.add_argument("--duration", type=float, default=None,
                   help="live mode: seconds to run before stopping (default: until Ctrl+C)")
    p.add_argument("--fields", default=None,
                   help="comma-separated fields to display (default: speed,rpm,power,current_distance). "
                        "e.g. --fields speed,rpm,power for the downscaled screen-capture demo where the "
                        "small center readouts don't survive OCR.")
    p.add_argument("--debug-save", default=None,
                   help="live mode: save the first captured frame here (to confirm what mss grabbed)")
    args = p.parse_args()

    if args.fields:
        global DISPLAY
        DISPLAY = [(f, FIELD_LABELS.get(f, f.upper())) for f in args.fields.split(",")]

    if args.live:
        if not args.region:
            raise SystemExit("--live requires --region left,top,width,height "
                             "(run `python live_source.py` to list monitor geometries)")
        try:
            l, t, w, h = (int(v) for v in args.region.split(","))
        except ValueError:
            raise SystemExit(f"Bad --region {args.region!r}; expected left,top,width,height")
        run_live(args.config, {"left": l, "top": t, "width": w, "height": h},
                 args.duration, args.fps, args.debug_save)
    else:
        run(args.video, args.config, args.start, args.end, args.fps, args.pace)


if __name__ == "__main__":
    main()
