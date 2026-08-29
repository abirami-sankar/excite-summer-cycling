import os as _os, sys as _sys  # handoff: allow running from debug-scripts/
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))

"""
channel_ocr.py

bisect_preprocess.py showed the read breaks at the grayscale step --
which usually means the HUD text and its background are distinguishable
by COLOR (hue) but not by standard luminance, so cv2.COLOR_BGR2GRAY's
weighted formula is flattening away contrast that's actually there in
the raw color image.

This script checks each individual color channel (and a couple of
alternative "grayscale" methods) to find which one keeps the contrast
that plain BGR2GRAY loses.

Usage:
    python channel_ocr.py --crop output/crop_power.png
"""

import argparse

import cv2
import numpy as np
import pytesseract

OCR_CONFIG = "--psm 7"


def ocr(image) -> str:
    return pytesseract.image_to_string(image, config=OCR_CONFIG).strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--crop", required=True, help="Path to a crop image to test")
    args = parser.parse_args()

    raw = cv2.imread(args.crop)
    if raw is None:
        raise SystemExit(f"Could not load {args.crop}")

    b, g, r = cv2.split(raw)
    standard_gray = cv2.cvtColor(raw, cv2.COLOR_BGR2GRAY)
    hsv = cv2.cvtColor(raw, cv2.COLOR_BGR2HSV)
    h, s, v = cv2.split(hsv)
    max_channel = np.max(raw, axis=2)  # brightest of B/G/R per pixel, unweighted

    print(f"Testing individual channels for: {args.crop}\n")
    print(f"standard grayscale (BGR2GRAY):  {ocr(standard_gray)!r}")
    print(f"blue channel:                    {ocr(b)!r}")
    print(f"green channel:                   {ocr(g)!r}")
    print(f"red channel:                     {ocr(r)!r}")
    print(f"HSV saturation channel:          {ocr(s)!r}")
    print(f"HSV value channel:               {ocr(v)!r}")
    print(f"max(B,G,R) per pixel:            {ocr(max_channel)!r}")

    print(
        "\nWhichever line above correctly reads the full expected value "
        "(e.g. '81W') is the channel to use instead of standard grayscale "
        "for this region -- swap that in as the first step of preprocess() "
        "for this field, in place of cv2.cvtColor(..., COLOR_BGR2GRAY)."
    )


if __name__ == "__main__":
    main()
    