"""
demo_overlay.py -- visual test of the Rouvy overlay (overlay.py).

Puts a transparent, click-through overlay on the target monitor and cycles
through the three element kinds -- a status chip, companion banners, and virtual
signs -- so you can confirm ON SCREEN that:
  * it draws on top of Rouvy,
  * text/signs are readable and correctly positioned,
  * the ride is NOT disrupted (you can still click / steer / use Rouvy
    underneath the overlay), and
  * it stays put (doesn't drift or fall behind).

Run with Rouvy riding (windowed/borderless) on the target monitor:
    python demo_overlay.py --region 1920,0,1920,1080 --duration 20

--region defaults to the campus-rig external monitor (see docs/campus-bike-1.md).
--duration auto-closes the overlay so it never gets stuck on top. --step sets
seconds between prompts. Use --region 0,0,1280,720 to test on the primary
screen without Rouvy.
"""

import argparse
import time

from overlay import RideOverlay


def parse_region(s):
    left, top, width, height = (int(v) for v in s.split(","))
    return {"left": left, "top": top, "width": width, "height": height}


# (kind, payload) -- signs carry (text, x_frac, y_frac). Stand-ins for the real
# experience beats: companion voice captions, landmark signs, artifact cards.
SCRIPT = [
    ("banner", "Welcome -- companion tour starting"),
    ("sign",   ("Snell Library  ->", 0.62, 0.42)),
    ("banner", "Landmark ahead: Centennial Common"),
    ("sign",   ("Photo spot", 0.30, 0.55)),
    ("banner", 'Artifact from Alice: "nice tree on your left!"'),
    ("sign",   ("<-  Turn here", 0.40, 0.48)),
]


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--region", default="1920,0,1920,1080")
    ap.add_argument("--duration", type=float, default=20.0,
                    help="seconds before auto-closing")
    ap.add_argument("--step", type=float, default=2.5,
                    help="seconds between prompts")
    ap.add_argument("--delay", type=float, default=0.0,
                    help="seconds to wait before showing the overlay (staging time)")
    args = ap.parse_args()

    if args.delay > 0:
        print(f"Starting overlay in {args.delay:.0f}s -- switch to the Rouvy monitor now.")
        time.sleep(args.delay)

    ov = RideOverlay(parse_region(args.region))
    ov.set_status("OVERLAY ACTIVE  -  ride not affected")

    state = {"i": 0, "elapsed": 0.0}

    def tick():
        kind, payload = SCRIPT[state["i"] % len(SCRIPT)]
        ov.clear_transient()
        if kind == "banner":
            ov.show_banner(payload)
        elif kind == "sign":
            text, xf, yf = payload
            ov.show_sign(text, xf, yf)
        state["i"] += 1
        state["elapsed"] += args.step
        if state["elapsed"] >= args.duration:
            ov.close()
            return
        ov.root.after(int(args.step * 1000), tick)

    print(f"Overlay on region {args.region} for {args.duration:.0f}s "
          f"({args.step}s/prompt). Confirm it draws over Rouvy and you can "
          f"still control the ride underneath.")
    ov.root.after(300, tick)
    ov.run()
    print("Overlay closed.")


if __name__ == "__main__":
    main()
