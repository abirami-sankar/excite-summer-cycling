"""
border.py

Small, standalone adapter: adds a white border around an image.

Kept separate from hud_reader.py so it's independently pluggable and
independently testable -- a border is a general image operation, not
something specific to HUD OCR.
"""

import cv2
import numpy as np


def add_white_border(image: np.ndarray, border_size: int = 10) -> np.ndarray:
    """Add a white border around image on all four sides.

    Tesseract's layout analysis assumes text has margin around it --
    digits touching the crop edge are a common cause of misreads/None
    results. This pads that margin back in before OCR ever sees the image.
    """
    return cv2.copyMakeBorder(
        image,
        top=border_size, bottom=border_size,
        left=border_size, right=border_size,
        borderType=cv2.BORDER_CONSTANT,
        value=0,  # white -- works for both grayscale and already-thresholded images
    )