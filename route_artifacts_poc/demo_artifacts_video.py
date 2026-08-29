"""
demo_artifacts_video.py

Renders a short, SHOWABLE clip of the route-artifacts POC for a team check-in
(companion to the terminal walkthrough in demo_artifacts.py). It plays the
real Rouvy ride footage and, as the rider advances, pops up a card each time
they reach an artifact that a PREVIOUS rider left on the route -- exactly the
"drop -> persist -> discover" loop from route_artifacts.py, visualized.

How position is obtained: the rider's route position is read LIVE off the HUD
with the real OCR pipeline (hud_reader on current_distance), every
--ocr-every frames, with the same light monotonic guard demo_v1.py uses so a
single misread can't jump the odometer or fire a bogus discovery. So what you
see is driven by actual OCR, not a scripted timeline.

The ride covers only ~0.29 km over 60s, and the seeded artifacts sit across
that range, so the clip is SPED UP (--speed, default 3x) to fit all the
discoveries into ~20s. Output frames are written at the source fps; speed-up
is done by sampling every Nth source frame.

Usage (run from anywhere):
    python route_artifacts_poc/demo_artifacts_video.py           # -> output/demo_artifacts.mp4
    python route_artifacts_poc/demo_artifacts_video.py --speed 3 --out output/demo_artifacts.mp4
"""

import argparse
import os
import sys

import cv2

_HERE = os.path.dirname(os.path.abspath(__file__))
_PROJ = os.path.dirname(_HERE)
sys.path.insert(0, _PROJ)   # so we can import the pipeline's hud_reader

import hud_reader                                    # noqa: E402
from route_artifacts import ArtifactDiscoverer, ArtifactStore  # noqa: E402

ROUTE_ID = "brookline-north"

# Artifacts a PREVIOUS rider group left along the route -- the current rider
# (Carol) discovers these. Positioned within the clip's 5.64->5.93 km range.
SEED = [
    (5.72, "Alice", "Nice tree on your left here!"),
    (5.80, "Bob",   "Bob was here -- wave!"),
    (5.88, "Alice", "Halfway up the hill, keep going"),
]

FONT = cv2.FONT_HERSHEY_SIMPLEX
WHITE = (255, 255, 255)
ACCENT = (80, 200, 255)   # amber-ish (BGR) for the artifact pin/card
DARK = (25, 25, 25)


def seed_store(store_path):
    """Fresh seed each run so the clip is reproducible."""
    if os.path.exists(store_path):
        os.remove(store_path)
    store = ArtifactStore(store_path)
    for pos, author, text in SEED:
        store.drop(ROUTE_ID, pos, text, author=author)
    store.save()
    return store.artifacts_for(ROUTE_ID)


def accept_distance(new, last):
    """Monotonic guard (mirrors demo_v1.py): reject implausible OCR jumps."""
    if not isinstance(new, tuple):
        return last
    if last is None:
        return new
    if 0.0 <= new[0] - last[0] <= 0.2:
        return new
    return last


def _panel(frame, x0, y0, x1, y1, alpha=0.72):
    """Draw a translucent dark panel in place (for readable overlays)."""
    sub = frame[y0:y1, x0:x1]
    if sub.size:
        dark = sub.copy()
        dark[:] = DARK
        frame[y0:y1, x0:x1] = cv2.addWeighted(dark, alpha, sub, 1 - alpha, 0)


def draw_hud(frame, km, found, total):
    """Persistent bottom strip: title, current km, discovery counter."""
    h, w = frame.shape[:2]
    _panel(frame, 0, h - 70, w, h)
    cv2.putText(frame, "ROUTE ARTIFACTS  -  POC", (30, h - 28),
                FONT, 0.8, WHITE, 2, cv2.LINE_AA)
    km_txt = f"{km:.2f} km" if km is not None else "-- km"
    cv2.putText(frame, km_txt, (w // 2 - 70, h - 28), FONT, 0.9, ACCENT, 2, cv2.LINE_AA)
    cv2.putText(frame, f"artifacts found: {found}/{total}", (w - 360, h - 28),
                FONT, 0.8, WHITE, 2, cv2.LINE_AA)


def draw_card(frame, artifact):
    """Center-top popup shown when an artifact is discovered."""
    h, w = frame.shape[:2]
    cw, ch = 900, 200
    x0, y0 = (w - cw) // 2, 90
    _panel(frame, x0, y0, x0 + cw, y0 + ch, alpha=0.8)
    cv2.rectangle(frame, (x0, y0), (x0 + cw, y0 + ch), ACCENT, 3)
    # pin marker
    cv2.circle(frame, (x0 + 55, y0 + 60), 20, ACCENT, cv2.FILLED)
    cv2.circle(frame, (x0 + 55, y0 + 60), 20, WHITE, 2)

    cv2.putText(frame, f"ARTIFACT FOUND  -  from {artifact.author}",
                (x0 + 95, y0 + 55), FONT, 0.95, ACCENT, 2, cv2.LINE_AA)
    cv2.putText(frame, f'"{artifact.payload}"', (x0 + 40, y0 + 120),
                FONT, 1.0, WHITE, 2, cv2.LINE_AA)
    cv2.putText(frame, f"left at {artifact.position_km:.2f} km  ({artifact.kind})",
                (x0 + 40, y0 + 170), FONT, 0.7, (200, 200, 200), 1, cv2.LINE_AA)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--video", default=os.path.join(_PROJ, "data", "training", "trimmed-video.mp4"))
    ap.add_argument("--config", default=os.path.join(_PROJ, "configs", "hud_config.json"))
    ap.add_argument("--out", default=os.path.join(_PROJ, "output", "demo_artifacts.mp4"))
    ap.add_argument("--store", default=os.path.join(_PROJ, "output", "demo_artifacts_seed.json"))
    ap.add_argument("--speed", type=int, default=3,
                    help="Speed-up factor: keep every Nth source frame (default: 3 -> ~20s)")
    ap.add_argument("--ocr-every", type=int, default=3,
                    help="Run OCR every N KEPT frames, hold in between (default: 3)")
    ap.add_argument("--banner-seconds", type=float, default=2.5,
                    help="How long a discovery card stays up (default: 2.5s)")
    args = ap.parse_args()

    config = hud_reader.load_config(args.config)
    artifacts = seed_store(args.store)
    discoverer = ArtifactDiscoverer(artifacts)

    cap = cv2.VideoCapture(args.video)
    if not cap.isOpened():
        raise SystemExit(f"Could not open video: {args.video}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    writer = cv2.VideoWriter(args.out, cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h))
    if not writer.isOpened():
        raise SystemExit(f"Could not open VideoWriter for {args.out}")

    spec = config["current_distance"]
    km_reading = None
    card = None
    card_frames_left = 0
    found = 0
    events = []

    src_idx = 0     # index into source frames
    kept = 0        # index into frames we actually write (the sped-up timeline)
    written = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if src_idx % args.speed != 0:   # sample for the speed-up
            src_idx += 1
            continue

        if kept % args.ocr_every == 0:
            raw = hud_reader.read_region(frame, spec["box"], spec["type"],
                                         spec.get("threshold"), spec.get("psm", 7))
            km_reading = accept_distance(raw, km_reading)
            km = km_reading[0] if isinstance(km_reading, tuple) else None
            for a in discoverer.advance(km):
                found += 1
                card = a
                card_frames_left = int(args.banner_seconds * fps)
                events.append((round(written / fps, 1), a.author, a.payload))

        km = km_reading[0] if isinstance(km_reading, tuple) else None
        if card_frames_left > 0:
            draw_card(frame, card)
            card_frames_left -= 1
        draw_hud(frame, km, found, len(artifacts))

        writer.write(frame)
        written += 1
        kept += 1
        src_idx += 1

    cap.release()
    writer.release()

    print(f"Wrote {args.out}: {written} frames ({written / fps:.1f}s @ {fps:.0f} fps, "
          f"{args.speed}x speed).")
    print(f"Discovered {found}/{len(artifacts)} artifacts:")
    for t, author, text in events:
        print(f"  t={t}s  {author}: \"{text}\"")


if __name__ == "__main__":
    main()
