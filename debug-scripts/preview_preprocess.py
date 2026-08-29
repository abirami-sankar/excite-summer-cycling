import os as _os, sys as _sys  # handoff: allow running from debug-scripts/
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))

"""
preview_preprocess.py

Debug tool: runs preprocess() on one or more crop images and saves the
processed (grayscale + thresholded + upscaled) result, so you can look
at exactly what Tesseract sees before it runs OCR.

This is separate from hud_reader.py on purpose -- preprocess() itself
stays a pure function with no required side effects, and this script is
the one place that opts into saving debug output.

Usage (preprocessed output now goes under output/, not a separate
preprocessed/ dir -- the two were consolidated):
    # Single image
    python preview_preprocess.py --crop output/crop_speed.png --preprodir output

    # Every crop_*.png in a directory
    python preview_preprocess.py --cropdir ./output --preprodir output
"""

import argparse
import glob
import os
import sys

import cv2

from hud_reader import preprocess


def process_one(crop_path: str, preprodir: str):
    image = cv2.imread(crop_path)
    if image is None:
        print(f"[skip] Could not load {crop_path}")
        return

    name = os.path.splitext(os.path.basename(crop_path))[0]
    save_path = os.path.join(preprodir, f"{name}_preprocessed.png")
    preprocess(image, save_path=save_path)
    print(f"Saved: {save_path}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--crop", help="Path to a single crop image")
    parser.add_argument("--cropdir", help="Directory containing crop_*.png images")
    parser.add_argument("--preprodir", required=True,
                         help="Directory to save preprocessed images into (created if missing)")
    args = parser.parse_args()

    if not args.crop and not args.cropdir:
        sys.exit("Provide either --crop <file> or --cropdir <directory>")

    os.makedirs(args.preprodir, exist_ok=True)

    if args.crop:
        process_one(args.crop, args.preprodir)

    if args.cropdir:
        paths = sorted(glob.glob(os.path.join(args.cropdir, "crop_*.png")))
        if not paths:
            print(f"No crop_*.png files found in {args.cropdir}")
        for path in paths:
            process_one(path, args.preprodir)


if __name__ == "__main__":
    main()