"""
HUD coordinate finder.

Step 1: Dump a frame from your video with a labeled pixel grid overlay.
         Open the saved image and read off the approximate (x, y) box
         corners for each HUD stat (speed, power, cadence, etc.) by eye.

Step 2: Once you have a guess at a box, use --preview to crop exactly
         that box out of the frame and save it separately, so you can
         check it tightly frames just the digits (no extra background,
         no clipped edges) before wiring it into the real pipeline.

Step 3: Once your boxes are confirmed and saved in a config JSON (see
         hud_reader.load_config()'s expected shape), use --config to
         re-crop every region from that file in one go -- no more
         retyping coordinates by hand for every new test frame.

Usage:
    # Step 1: dump a grid-overlaid frame to inspect
    python find_hud_coords.py --video ride.mp4 --time 30 --grid

    # Step 2: preview a candidate crop box (x1,y1,x2,y2 in pixels)
    python find_hud_coords.py --video ride.mp4 --time 30 \
        --preview speed=1600,950,1700,990

    # Step 3: re-crop every region from a saved config, at a new timestamp
    python find_hud_coords.py --video ride.mp4 --time 90 \
        --config configs/hud_config.json

Both steps read the same frame (by --time in seconds) so what you see
lines up between the grid image and the crop preview.
"""

import argparse
import json
import os
import sys

import cv2


def grab_frame(video_path: str, time_sec: float):
    """Return a single frame (as a numpy array) from video_path at time_sec."""
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        sys.exit(f"Could not open video: {video_path}")

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    frame_index = int(time_sec * fps)
    cap.set(cv2.CAP_PROP_POS_FRAMES, frame_index)

    ok, frame = cap.read()
    cap.release()
    if not ok:
        sys.exit(
            f"Could not read a frame at t={time_sec}s "
            f"(video may be shorter than that, or corrupt)."
        )
    return frame


def draw_grid(frame, step: int = 50):
    """Return a copy of frame with a labeled pixel grid drawn on top."""
    out = frame.copy()
    h, w = out.shape[:2]

    color = (0, 255, 0)
    text_color = (0, 255, 255)
    thickness = 1

    for x in range(0, w, step):
        cv2.line(out, (x, 0), (x, h), color, thickness)
        cv2.putText(out, str(x), (x + 2, 15), cv2.FONT_HERSHEY_SIMPLEX,
                    0.4, text_color, 1, cv2.LINE_AA)

    for y in range(0, h, step):
        cv2.line(out, (0, y), (w, y), color, thickness)
        cv2.putText(out, str(y), (2, y + 12), cv2.FONT_HERSHEY_SIMPLEX,
                    0.4, text_color, 1, cv2.LINE_AA)

    return out


def parse_box(spec: str):
    """Parse 'name=x1,y1,x2,y2' into (name, (x1, y1, x2, y2))."""
    try:
        name, coords = spec.split("=")
        x1, y1, x2, y2 = (int(v) for v in coords.split(","))
        return name, (x1, y1, x2, y2)
    except ValueError:
        sys.exit(
            f"Bad --preview value: {spec!r}. "
            f"Expected format name=x1,y1,x2,y2 e.g. speed=1600,950,1700,990"
        )


def load_boxes_from_config(path: str) -> dict:
    """Read {name: (x1,y1,x2,y2)} out of a hud_reader-style config JSON.

    Only pulls the "box" field -- "type" is hud_reader's concern, not
    this script's. Kept as a plain json.load (not hud_reader.load_config)
    so this script has no hard dependency on hud_reader's type validation;
    a box with a type hud_reader doesn't recognize yet shouldn't stop you
    from previewing the crop.
    """
    with open(path) as f:
        raw = json.load(f)

    boxes = {}
    for name, spec in raw.items():
        try:
            x1, y1, x2, y2 = spec["box"]
        except (KeyError, ValueError):
            sys.exit(f"Config entry '{name}' is missing a valid 4-value 'box' field.")
        boxes[name] = (x1, y1, x2, y2)
    return boxes


def save_crop(frame, name: str, box: tuple, outdir: str):
    """Crop `box` out of frame and save it as crop_<name>.png in outdir."""
    x1, y1, x2, y2 = box
    crop = frame[y1:y2, x1:x2]
    if crop.size == 0:
        print(f"[{name}] WARNING: empty crop -- check your coordinates are within frame bounds")
        return
    out_path = os.path.join(outdir, f"crop_{name}.png")
    cv2.imwrite(out_path, crop)
    print(f"Saved crop '{name}': {out_path} ({x2-x1}x{y2-y1}px)")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video", default=None, help="Path to the input video file")
    parser.add_argument("--image", default=None,
                         help="Path to a static image to use as the frame instead of a video "
                              "(e.g. a snapshot from live_source.py). Use this to check whether "
                              "your existing hud_config.json boxes still line up against a live "
                              "capture before assuming OCR itself is broken -- one of --video or "
                              "--image is required.")
    parser.add_argument("--time", type=float, default=30.0,
                         help="Video mode only: timestamp in seconds to grab the sample frame "
                              "from (default: 30)")
    parser.add_argument("--grid", action="store_true",
                         help="Save the frame with a pixel grid overlay for coordinate hunting")
    parser.add_argument("--grid-step", type=int, default=50,
                         help="Spacing in pixels between gridlines (default: 50)")
    parser.add_argument("--preview", action="append", default=[],
                         help="name=x1,y1,x2,y2 -- crop and save this box for verification. "
                              "Can be passed multiple times.")
    parser.add_argument("--config", default=None,
                         help="Path to a hud_reader-style config JSON (e.g. hud_config.json). "
                              "Crops every region's box from this file in one go -- use this "
                              "once your regions are confirmed, instead of retyping --preview "
                              "for every new test frame.")
    parser.add_argument("--outdir", default=".", help="Directory to save output images to")
    args = parser.parse_args()

    if not args.video and not args.image:
        sys.exit("One of --video or --image is required.")
    if args.video and args.image:
        sys.exit("Pass only one of --video or --image, not both.")

    os.makedirs(args.outdir, exist_ok=True)

    if args.image:
        frame = cv2.imread(args.image)
        if frame is None:
            sys.exit(f"Could not read image: {args.image}")
    else:
        frame = grab_frame(args.video, args.time)

    if args.grid:
        grid_frame = draw_grid(frame, step=args.grid_step)
        out_path = os.path.join(args.outdir, "frame_grid.png")
        cv2.imwrite(out_path, grid_frame)
        print(f"Saved grid overlay: {out_path}")
        print("Open it and read off approximate box corners for each HUD stat.")

    if not args.preview and not args.config and not args.grid:
        # Default behavior if the user passed none of the flags: just dump the raw frame.
        out_path = os.path.join(args.outdir, "frame_raw.png")
        cv2.imwrite(out_path, frame)
        print(f"Saved raw frame: {out_path}")
        print("Re-run with --grid to overlay pixel coordinates.")

    for spec in args.preview:
        name, box = parse_box(spec)
        save_crop(frame, name, box, args.outdir)

    if args.config:
        boxes = load_boxes_from_config(args.config)
        print(f"Loaded {len(boxes)} region(s) from {args.config}")
        for name, box in boxes.items():
            save_crop(frame, name, box, args.outdir)


if __name__ == "__main__":
    main()