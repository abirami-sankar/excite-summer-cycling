import os as _os, sys as _sys  # handoff: allow running from debug-scripts/
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))

"""
bisect_preprocess.py

preview_preprocess.py showed you the FINAL preprocessed image looks fine
visually, but diagnose_ocr.py showed OCR still fails on it. That means
the failure is happening at some INTERMEDIATE step, not something
visible in the final image alone (e.g. an upscale interpolation
artifact that's subtle to the eye but confuses Tesseract's internal
segmentation).

This script runs OCR after each individual step in the preprocessing
chain, so you can see exactly where the read breaks:

    stage 0: raw crop (no processing)
    stage 1: + grayscale
    stage 2: + threshold (Otsu)
    stage 3: + resize/upscale (current: INTER_CUBIC)
    stage 4: + resize/upscale using INTER_NEAREST instead (comparison --
              cubic interpolation can introduce ringing/halo artifacts
              on binary text images that INTER_NEAREST does not)

Usage:
    python bisect_preprocess.py --crop output/crop_power.png
"""

import argparse

import cv2
import pytesseract

# No whitelist -- we want to see the actual characters Tesseract finds
# at each stage, not have a whitelist mask the difference.
OCR_CONFIG = "--psm 7"


def ocr(image) -> str:
    return pytesseract.image_to_string(image, config=OCR_CONFIG).strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--crop", required=True, help="Path to a crop image to bisect")
    args = parser.parse_args()

    raw = cv2.imread(args.crop)
    if raw is None:
        raise SystemExit(f"Could not load {args.crop}")

    print(f"Bisecting preprocessing for: {args.crop}\n")

    # Stage 0: raw
    print(f"stage 0 (raw crop):                    {ocr(raw)!r}")

    # Stage 1: + grayscale
    gray = cv2.cvtColor(raw, cv2.COLOR_BGR2GRAY)
    print(f"stage 1 (+ grayscale):                  {ocr(gray)!r}")

    # Stage 2: + threshold (Otsu)
    _, bw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    print(f"stage 2 (+ Otsu threshold):             {ocr(bw)!r}")

    # Stage 3: + resize using current method (cubic)
    upscaled_cubic = cv2.resize(bw, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
    print(f"stage 3 (+ resize, INTER_CUBIC):        {ocr(upscaled_cubic)!r}")

    # Stage 4: same resize, but with nearest-neighbor interpolation instead --
    # a direct comparison to see if the interpolation method itself is the
    # difference-maker.
    upscaled_nearest = cv2.resize(bw, None, fx=3, fy=3, interpolation=cv2.INTER_NEAREST)
    print(f"stage 4 (+ resize, INTER_NEAREST cmp):  {ocr(upscaled_nearest)!r}")

    print(
        "\nWhichever stage's output first differs from the one before it is "
        "where the read breaks -- that pinpoints the exact step to fix, "
        "rather than the whole preprocess() function."
    )


if __name__ == "__main__":
    main()