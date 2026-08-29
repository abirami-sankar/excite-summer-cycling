"""
hud_reader.py

Core OCR logic for reading HUD stats out of a video frame.

Deliberately has NO knowledge of video files, live streams, or timing --
it only knows how to turn (frame, box, type) -> a parsed value. That's
what makes it testable with plain static images, and reusable unchanged
whether the frame came from a recorded file or a live source later.

Each region declares its own type ("int", "float", "str", or
"unit_value") in the config, since different HUD fields need different
OCR whitelists and different parsing:
    - "int"        e.g. cadence           -> 22
    - "float"      e.g. speed             -> 27.8
    - "str"        e.g. gear label, zone  -> "L3"
    - "unit_value" e.g. power, distance   -> (5.68, "km")

"unit_value" is for fields where the HUD bakes a unit into the same
crop as the number (e.g. "5.68 km", "7W", "29m"). It deliberately uses
NO whitelist -- like "str" -- because restricting Tesseract's character
set to digits would blind it to the unit letters and risk misreading
the whole crop. The number/unit split happens *after* OCR, in Python,
not by constraining what Tesseract is allowed to see.
"""

import json
import os
import re
from typing import Optional, Union
import border
import cv2
import numpy as np
import pytesseract

ParsedValue = Union[int, float, str, tuple, None]

# One whitelist + one parser per type. Adding a new type later means
# adding one entry here -- nothing else in this file needs to change.
_TYPE_SPECS = {
    "int": {
        "whitelist": "0123456789-",
        "parse": lambda s: int(s) if s.lstrip("-").isdigit() else None,
    },
    "float": {
        "whitelist": "0123456789.-",
        "parse": lambda s: _parse_float(s),
    },
    "str": {
        "whitelist": None,  # no restriction -- letters and digits both allowed
        "parse": lambda s: s if s else None,
    },
    "unit_value": {
        "whitelist": None,  # no restriction -- same reasoning as "str"
        "parse": lambda s: _parse_unit_value(s),
    },
}


def _parse_float(s: str) -> Optional[float]:
    try:
        return float(s)
    except ValueError:
        return None


# Matches the FIRST run of digits (optionally decimal) anywhere in the
# string, then whatever text follows as the unit -- with or without a
# space in between, so both "29m" and "98 m" parse the same way.
#
# We SEARCH (not anchor at start) and do NOT accept a leading sign, on
# purpose: some crops pick up a spurious leading character before the
# number that OCR reads as "-" (e.g. the blue lightning-bolt icon just
# left of the power number). unit_value fields are all NON-NEGATIVE --
# no current HUD unit_value field (power, distance, elevation) is ever
# signed -- so skipping any junk ahead of the first digit run is always
# the right call. Revisit only if a genuinely signed unit_value is added.
_UNIT_VALUE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(.*)$")

# Common Tesseract digit/letter confusions for fixed-font digital displays.
# Safe to apply across the WHOLE unit_value string only because none of
# our actual unit labels (W, km, m) contain any of these letters -- if a
# future unit does (e.g. "bar", "Ohm"), this blanket approach would need
# to get smarter about only correcting the numeric prefix.
_CONFUSABLE_DIGIT_MAP = str.maketrans({
    "O": "0", "o": "0",
    "B": "8",
    "S": "5", "s": "5",
    "Z": "2", "z": "2",
    "G": "6",
    "I": "1", "l": "1", "i": "1", "L": "1",
    "T": "7",
    "A": "4",
})


def _fix_confusable_digits(s: str) -> str:
    return s.translate(_CONFUSABLE_DIGIT_MAP)


def _parse_unit_value(s: str) -> Optional[tuple]:
    s = _fix_confusable_digits(s.strip())
    match = _UNIT_VALUE_RE.search(s)
    if not match:
      return None

    number_str, unit = match.groups()
    number = float(number_str) if "." in number_str else int(number_str)
    unit = unit.strip()
    if not unit:
      return (number, s)
    return (number, unit)


def _tesseract_config(region_type: str, psm: int = 7) -> str:
    whitelist = _TYPE_SPECS[region_type]["whitelist"]
    base = f"--psm {psm}"
    if whitelist is None:
        return base
    return f"{base} -c tessedit_char_whitelist={whitelist}"


def load_config(path: str) -> dict:
    """Load a region config from a JSON file.

    Expected shape:
        {
          "speed":    {"box": [x1, y1, x2, y2], "type": "int"},
          "gradient": {"box": [x1, y1, x2, y2], "type": "float"},
          "gear":     {"box": [x1, y1, x2, y2], "type": "str"}
        }
    """
    with open(path) as f:
        raw = json.load(f)

    config = {}
    for name, spec in raw.items():
        region_type = spec.get("type", "int")
        if region_type not in _TYPE_SPECS:
            raise ValueError(
                f"Region '{name}' has unknown type '{region_type}'. "
                f"Must be one of: {list(_TYPE_SPECS)}"
            )
        entry = {"box": tuple(spec["box"]), "type": region_type}
        # Optional per-region fixed threshold (default: Otsu, see preprocess()).
        if "threshold" in spec:
            entry["threshold"] = spec["threshold"]
        # Optional per-region Tesseract page-segmentation mode (default: 7,
        # a single text line). Some regions read better under a different
        # mode -- e.g. the heavily-italic power number needs psm 8 (treat
        # as a single word), which psm 7 consistently misreads.
        if "psm" in spec:
            entry["psm"] = spec["psm"]
        config[name] = entry
    return config


def preprocess(crop: np.ndarray, save_path: Optional[str]=None,
               threshold: Optional[int]=None) -> np.ndarray:
    """Grayscale + threshold + upscale a cropped HUD region for OCR.

    This step matters more than the OCR call itself for fixed-font
    digital displays: a clean black/white, upscaled image removes most
    of the misreads before Tesseract ever runs.

    Note on the "grayscale" step: this deliberately does NOT use
    cv2.cvtColor(..., COLOR_BGR2GRAY). That function applies a WEIGHTED
    luminance formula, which can flatten away contrast between
    differently-colored text and background even when they're clearly
    distinct to the eye (confirmed via bisection: some HUD regions read
    correctly raw but failed after standard grayscale conversion --
    e.g. blue-tinted unit labels losing contrast against a dark
    background). Taking max(B,G,R) per pixel instead is color-agnostic --
    whichever channel is brightest at a given pixel dominates, regardless
    of hue, so it doesn't assume any particular text color per region.

    Thresholding: `threshold=None` (the default) uses Otsu, which picks a
    cutoff automatically and works for regions sitting on a plain/dark
    background. But some regions have BRIGHT graphics directly BEHIND the
    text (the elevation numbers sit on top of the colored route-profile
    graphic, not just below a separable band), and there Otsu's
    whole-crop cutoff gets pulled toward the graphic and corrupts the
    digits. For those regions a FIXED high threshold (e.g. 190) keeps
    only the near-white text and drops the mid-brightness graphic behind
    it -- confirmed on current_elevation, where Otsu read '239'/'32' but
    a fixed 190 reads '29'/'32' correctly. Set it per-region in the config.
    """

    max_channel = np.max(crop, axis=2)
    if threshold is None:
        # Otsu: automatic cutoff, robust to a semi-transparent overlay on
        # a plain background.
        _, bw = cv2.threshold(max_channel, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    else:
        # Fixed cutoff: keep only pixels brighter than `threshold`, to
        # isolate near-white text from a bright graphic behind it.
        _, bw = cv2.threshold(max_channel, threshold, 255, cv2.THRESH_BINARY)
   # bw = border.add_white_border(bw)
    upscaled = cv2.resize(bw, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)

    if save_path is not None:
        os.makedirs(os.path.dirname(save_path) or ".", exist_ok=True)
        cv2.imwrite(save_path, upscaled)

    return upscaled


def read_region(frame: np.ndarray, box: tuple, region_type: str = "int",
                threshold: Optional[int] = None, psm: int = 7) -> ParsedValue:
    """Crop one box out of frame, OCR it, and parse according to region_type.

    Returns None if the crop is empty or nothing parseable came out --
    callers decide what a None means (e.g. fall back to the last good
    reading). This function's job is just an honest "readable" or "not
    readable," not to paper over failures.

    `threshold` is passed straight to preprocess(): None = Otsu (default),
    or a fixed cutoff for regions with a bright graphic behind the text.

    `psm` is the Tesseract page-segmentation mode (default 7 = single
    text line); pass 8 (single word) for regions psm 7 misreads, e.g. the
    italic power number.
    """
    if region_type not in _TYPE_SPECS:
        raise ValueError(f"Unknown region_type '{region_type}'. Must be one of: {list(_TYPE_SPECS)}")

    x1, y1, x2, y2 = box
    crop = frame[y1:y2, x1:x2]
    if crop.size == 0:
        return None

    processed = preprocess(crop, threshold=threshold)
    text = pytesseract.image_to_string(processed, config=_tesseract_config(region_type, psm))
    cleaned = text.strip()

    if not cleaned:
        return None
    return _TYPE_SPECS[region_type]["parse"](cleaned)


def extract_hud(frame: np.ndarray, config: dict) -> dict:
    """Read every region in config out of frame.

    config shape matches load_config()'s output:
        {name: {"box": (x1,y1,x2,y2), "type": "int"|"float"|"str"|"unit_value"}}

    Returns {name: parsed_value_or_None}.
    """
    return {
        name: read_region(frame, spec["box"], spec["type"],
                          spec.get("threshold"), spec.get("psm", 7))
        for name, spec in config.items()
    }