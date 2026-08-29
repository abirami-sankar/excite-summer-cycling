"""
demo_experience.py -- v1 experience-design video artifact (the dwell-tour probe).

Renders the "Curry -> After Hours concert" marker beat over REAL campus footage
(data/training/RouvyCampusTest.mp4, ~3:10): as the rider approaches, a left-side virtual
sign fades in with generic music; as they ride past, both fade out ("the music
fades behind you..."). This is the PASSED branch of the pause-aware dwell-tour
loop (see docs/feature-poc-dwell-tour.md) -- the audio-proximity lure that a
rider can either stop for (dwell payoff, a later beat) or ride past.

Scripted-by-timestamp for v1 (the recorded rider never actually stops, and we
have no campus stream_hud JSONL yet); real-OCR-driven triggering is the next
iteration. Music is the uploaded generic clip (data/mondamusic-...mp3); ffmpeg
applies the approach/pass fades (afade) as it muxes.

Pipeline: cv2 renders the silent overlay beat with time-varying alpha -> bundled
ffmpeg fades + muxes the mp3 onto it. Output: output/demo_experience_v1.mp4
(gitignored; regenerate with `python demo_experience.py`).

Deps: moviepy was installed only for its bundled ffmpeg (imageio_ffmpeg); this
script uses the ffmpeg binary directly, not the moviepy API.
"""

import argparse
import glob
import os
import subprocess

import cv2
import imageio_ffmpeg

BASE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(BASE, "data", "training", "RouvyCampusTest.mp4")
OUT = os.path.join(BASE, "output")
SILENT = os.path.join(OUT, "_exp_silent.mp4")
# the uploaded generic music clip (retro/arcade bed for the "concert")
_MP3S = glob.glob(os.path.join(BASE, "data", "prototype-demo", "*mondamusic*.mp3")) or \
        glob.glob(os.path.join(BASE, "data", "prototype-demo", "*.mp3"))
MP3 = _MP3S[0] if _MP3S else None
FINAL = os.path.join(OUT, "demo_experience_v1.mp4")
FF = imageio_ffmpeg.get_ffmpeg_exe()
W, H, FPS = 1280, 720, 30
FONT = cv2.FONT_HERSHEY_DUPLEX


def bgr(h):
    h = h.lstrip("#")
    return (int(h[4:6], 16), int(h[2:4], 16), int(h[0:2], 16))


def alpha(t, a, b, c, d):
    """Trapezoid: fade in over [a,b], hold to c, fade out over [c,d]."""
    if t < a or t >= d:
        return 0.0
    if t < b:
        return (t - a) / (b - a)
    if t < c:
        return 1.0
    return 1 - (t - c) / (d - c)


def blend(frame, a, draw):
    if a <= 0.01:
        return
    layer = frame.copy()
    draw(layer)
    cv2.addWeighted(layer, a, frame, 1 - a, 0, dst=frame)


def _sign(layer):
    x1, y1, w, h = 40, 250, 690, 150
    cv2.rectangle(layer, (x1, y1), (x1 + w, y1 + h), bgr("#7c2d12"), -1)
    cv2.rectangle(layer, (x1, y1), (x1 + 12, y1 + h), bgr("#f59e0b"), -1)
    cv2.putText(layer, "<-  this way: Curry Student Center", (x1 + 30, y1 + 58),
                FONT, 0.82, bgr("#ffffff"), 2, cv2.LINE_AA)
    cv2.putText(layer, "After Hours concert - live music", (x1 + 30, y1 + 108),
                FONT, 0.72, bgr("#fde68a"), 1, cv2.LINE_AA)


def _status(layer):
    cv2.rectangle(layer, (24, 24), (210, 64), bgr("#065f46"), -1)
    cv2.putText(layer, "COMPANION", (38, 52), FONT, 0.7, bgr("#d1fae5"), 1, cv2.LINE_AA)


def _endcap(layer):
    txt = "the music fades behind you..."
    (tw, _), _ = cv2.getTextSize(txt, FONT, 0.9, 2)
    x = (W - tw) // 2
    cv2.rectangle(layer, (x - 24, H - 96), (x + tw + 24, H - 40), bgr("#111827"), -1)
    cv2.putText(layer, txt, (x, H - 56), FONT, 0.9, bgr("#ffffff"), 2, cv2.LINE_AA)


def render_silent(start, dur):
    cap = cv2.VideoCapture(SRC)
    sfps = cap.get(cv2.CAP_PROP_FPS) or 30
    cap.set(cv2.CAP_PROP_POS_FRAMES, int(start * sfps))
    vw = cv2.VideoWriter(SILENT, cv2.VideoWriter_fourcc(*"mp4v"), FPS, (W, H))
    for i in range(int(dur * FPS)):
        ok, fr = cap.read()
        if not ok:
            break
        fr = cv2.resize(fr, (W, H))
        t = i / FPS
        blend(fr, 0.9, _status)
        blend(fr, alpha(t, 1.0, 3.0, 12.0, 16.0), _sign)
        blend(fr, alpha(t, 13.0, 14.5, 16.0, 17.8), _endcap)
        vw.write(fr)
    vw.release()
    cap.release()


def mux(dur, music_start):
    """Mux the mp3 onto the silent video, fading it in on approach / out on pass."""
    if MP3 is None:
        raise SystemExit("No .mp3 found in data/ for the music bed.")
    fade_out_at = max(0.0, dur - 4.5)
    afade = f"afade=t=in:st=0:d=2.5,afade=t=out:st={fade_out_at}:d=4.5"
    subprocess.run([FF, "-y", "-loglevel", "error",
                    "-i", SILENT,
                    "-ss", str(music_start), "-t", str(dur), "-i", MP3,
                    "-filter_complex", f"[1:a]{afade}[a]",
                    "-map", "0:v", "-map", "[a]",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-b:a", "192k", "-shortest", FINAL], check=True)


def verify_audible():
    """Confirm the muxed audio is actually AUDIBLE (not just a present stream)."""
    r = subprocess.run([FF, "-i", FINAL, "-af", "volumedetect", "-f", "null", "-"],
                       capture_output=True, text=True)
    for line in r.stderr.splitlines():
        if "max_volume" in line or "mean_volume" in line:
            print("  " + line.split("] ")[-1].strip())


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--start", type=float, default=182.0, help="source start time (s)")
    ap.add_argument("--duration", type=float, default=18.0)
    ap.add_argument("--music-start", type=float, default=6.0,
                    help="offset into the mp3 to start from (skip any intro)")
    args = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)
    render_silent(args.start, args.duration)
    mux(args.duration, args.music_start)
    try:
        os.remove(SILENT)
    except OSError:
        pass
    print(f"Wrote {FINAL} ({os.path.getsize(FINAL) // 1024} KB, {args.duration:.0f}s).")
    verify_audible()


if __name__ == "__main__":
    main()
