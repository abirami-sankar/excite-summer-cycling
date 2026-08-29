import os as _os, sys as _sys  # handoff: allow running from debug-scripts/
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))

"""
diagnose_ocr.py

Root-cause tool for OCR misreads. Instead of guessing why a value came
out wrong, this shows you what's actually happening at each stage:

  1. RAW text with no character whitelist at all -- tells you whether
     Tesseract saw a character (e.g. "W") but your whitelist stripped it
     (expected, not a bug) vs never detected it in the first place.
  2. Per-character confidence -- low confidence on a specific digit
     points at a preprocessing/threshold problem for that digit, not a
     random fluke.
  3. Same crop run across several --psm (page segmentation) modes --
     if one psm mode consistently reads correctly and another doesn't,
     that's a segmentation assumption mismatch, not a font/threshold issue.

Usage:
    python diagnose_ocr.py --crop output/crop_power.png

This runs on an ALREADY-PREPROCESSED crop by default. To see the effect
of preprocessing itself, pass --raw to skip preprocessing and diagnose
the untouched crop instead.
"""

import argparse
from typing import Optional

import cv2
import pytesseract

from hud_reader import preprocess

# Common psm modes worth comparing for small HUD text regions:
#   6  = assume a single uniform block of text
#   7  = treat the image as a single text line (current default)
#   8  = treat the image as a single word
#  11  = sparse text, find as much as possible, no particular order
#  13  = raw line, bypass most layout heuristics
PSM_MODES_TO_TRY = [6, 7, 8, 11, 13]


def show_raw_text(image):
    print("\n--- Raw OCR text (no character whitelist) ---")
    text = pytesseract.image_to_string(image, config="--psm 7")
    print(f"  {text!r}")
    print("  (Compare this against your expected value + unit. If the unit/")
    print("   letter shows up here but not in your parsed result, your")
    print("   whitelist is stripping it as intended -- not a misread.)")


def show_confidence(image):
    print("\n--- Per-character confidence (--psm 7) ---")
    data = pytesseract.image_to_data(
        image, config="--psm 7", output_type=pytesseract.Output.DICT
    )
    found_any = False
    for text, conf in zip(data["text"], data["conf"]):
        if text.strip():
            found_any = True
            print(f"  text={text!r:8s} confidence={conf}")
    if not found_any:
        print("  (nothing detected at all -- likely a segmentation issue, see psm comparison below)")


def show_psm_comparison(image, whitelist: Optional[str]):
    label = whitelist if whitelist is not None else "(none)"
    print(f"\n--- Same crop across different --psm modes (whitelist={label!r}) ---")
    for psm in PSM_MODES_TO_TRY:
        config = f"--psm {psm}"
        if whitelist is not None:
            config += f" -c tessedit_char_whitelist={whitelist}"
        text = pytesseract.image_to_string(image, config=config).strip()
        print(f"  psm {psm:>2}: {text!r}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--crop", required=True, help="Path to a crop image to diagnose")
    parser.add_argument("--raw", action="store_true",
                         help="Skip preprocessing and diagnose the untouched crop")
    parser.add_argument("--whitelist", default="0123456789",
                         help="Character whitelist to use for the psm comparison (default: digits only)")
    parser.add_argument("--no-whitelist", action="store_true",
                         help="Use no character whitelist at all for the psm comparison "
                              "(equivalent to --whitelist \"\", without the shell quoting headache)")
    args = parser.parse_args()

    image = cv2.imread(args.crop)
    if image is None:
        raise SystemExit(f"Could not load {args.crop}")

    if not args.raw:
        image = preprocess(image)

    whitelist = None if args.no_whitelist else args.whitelist

    print(f"Diagnosing: {args.crop} (preprocessed={not args.raw})")
    show_raw_text(image)
    show_confidence(image)
    show_psm_comparison(image, whitelist)


if __name__ == "__main__":
    main()