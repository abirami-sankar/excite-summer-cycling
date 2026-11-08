"""
demo_audio_memories.py

Proof of concept for AUDIO MEMORIES that a past rider leaves behind and a LATER
rider HEARS in a new session -- the compelling half of the "social content"
feature. It ties three pieces together, each already proven on its own:

  * route_artifacts.py  -- persistence: an artifact pinned to a ROUTE POSITION
    survives process exit (here kind="audio", payload = a clip reference).
  * ArtifactDiscoverer  -- fires each memory ONCE as the rider reaches its spot
    (high-water-mark logic, robust to noisy OCR position).
  * audio_bed.AudioBed  -- plays / layers / fades the clips as they're crossed.

WHAT PLAYS -- two sources, merged by route position:
  1. demo_voices/ (project root): pre-recorded human voice clips for the study.
     Each file is pinned to the route by its NAME (see parse_voice_filename):
         300m_alice_good-luck-on-finals.mp3   -> 300 m, by alice
         1.05km_carol.wav                     -> 1050 m, by carol
         welcome.mp3   (no position prefix)   -> spaced evenly along the route
     Read fresh every run (NOT copied into the store), so renaming / removing a
     file just works. Supports .mp3 / .wav / .ogg.
  2. the persistent --store: voice clips riders recorded with
     demo_leave_message.py (plus any text trinkets, which are announced).

As the rider crosses each spot the clip fades IN; once past, it fades OUT. Two
clips close together overlap -> you hear them LAYERED.

Location-tied vs rider-tied: this demo is location-tied (memories pinned to the
route). A ghost-rider/bot is the SAME engine with a MOVING anchor instead of a
fixed one -- that's the next POC, not a rewrite.

Runs headless: with no audio device AudioBed no-ops and you still see the full
discovery trace. On a real machine you HEAR it -- which is what the rig is for.

Usage:
    python demo_audio_memories.py                 # synthetic ride, campus length
    python demo_audio_memories.py --speed 4       # 4x faster (less waiting)
    python demo_audio_memories.py --stream ../run.jsonl   # real OCR positions
    python demo_audio_memories.py --live --region 1920,0,1920,1080
"""

import argparse
import os
import re
import sys
import time

# audio_bed lives in the project root (this POC is a subfolder).
_PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _PROJ)

from audio_bed import AudioBed  # noqa: E402
from route_artifacts import Artifact, ArtifactDiscoverer, ArtifactStore  # noqa: E402

ROUTE_ID = "campus-loop"
TOTAL_KM = 1.344                 # campus route total (see CLAUDE.md invariant)
VOICES_DIR = os.path.join(_PROJ, "demo_voices")
AUDIO_EXTS = (".mp3", ".wav", ".ogg")

TRIGGER_RADIUS_KM = 0.03   # start the memory a touch BEFORE its spot (a lure)
PASS_KM = 0.10             # fade the memory out once this far past its spot
FADE_IN_MS = 700
FADE_OUT_MS = 1200

# "<number><m|km>" then a separator, then "<author>[_<caption words>]".
# A bare number (no unit) is metres -- the HUD's own unit on the campus loop.
_POS_RE = re.compile(r"^(\d+(?:\.\d+)?)\s*(km|m)?[ _-]+(.+)$", re.IGNORECASE)


# --- pure helpers (unit-tested) ----------------------------------------------

def parse_voice_filename(filename):
    """Pure: ``300m_alice_good-luck.mp3`` -> (0.3, "alice", "good luck").

    Returns (position_km or None, author, caption). position_km is None when
    the name has no position prefix (the caller spaces those evenly).
    """
    stem = os.path.splitext(os.path.basename(filename))[0]
    pos_km = None
    m = _POS_RE.match(stem)
    if m:
        num, unit, stem = float(m.group(1)), (m.group(2) or "m").lower(), m.group(3)
        pos_km = num if unit == "km" else num / 1000.0
    author, _, rest = stem.partition("_")
    caption = re.sub(r"[_-]+", " ", rest).strip()
    return pos_km, (author or "voice"), caption


def place_voices(parsed, total_km=TOTAL_KM):
    """Pure: [(filename, pos_km|None, author, caption)] -> same list with every
    position filled in. Unpositioned clips are spaced evenly (in name order)
    along the route; clips past the route end are dropped with a warning."""
    placed, unplaced = [], []
    for item in parsed:
        fn, pos, author, cap = item
        if pos is None:
            unplaced.append(item)
        elif 0.0 <= pos <= total_km:
            placed.append(item)
        else:
            print(f"  [voices] skip {fn}: {pos*1000:.0f} m is past the route end "
                  f"({total_km*1000:.0f} m)")
    n = len(unplaced)
    for i, (fn, _pos, author, cap) in enumerate(sorted(unplaced)):
        placed.append((fn, round(total_km * (i + 1) / (n + 1), 3), author, cap))
    return sorted(placed, key=lambda t: t[1])


def load_demo_voices(voices_dir=VOICES_DIR, total_km=TOTAL_KM):
    """Build in-memory audio Artifacts from the demo_voices folder; also return
    {clip path: caption} for the trace. Missing/empty folder -> nothing."""
    if not os.path.isdir(voices_dir):
        return [], {}
    names = sorted(f for f in os.listdir(voices_dir) if f.lower().endswith(AUDIO_EXTS))
    parsed = [(f, *parse_voice_filename(f)) for f in names]
    arts, captions = [], {}
    for i, (fn, pos, author, cap) in enumerate(place_voices(parsed, total_km)):
        path = os.path.join(voices_dir, fn)
        arts.append(Artifact(id=f"demo_voices:{fn}", route_id=ROUTE_ID,
                             position_km=pos, kind="audio", payload=path,
                             author=author, seq=-1 - i, created_at=""))
        captions[path] = cap or fn
    return arts, captions


# --- position sources --------------------------------------------------------

def synthetic_positions(step_km=0.01):
    km = 0.0
    while km <= TOTAL_KM + 1e-9:
        yield round(km, 3)
        km += step_km


def stream_positions(path):
    """current_distance (km) per frame from a stream_hud JSONL (real OCR path)."""
    import json
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            cd = json.loads(line).get("readings", {}).get("current_distance")
            if isinstance(cd, list) and cd and isinstance(cd[0], (int, float)):
                yield float(cd[0])


def live_positions(region_str, config_path, period=0.4):
    """Yield live current_distance (km) off Rouvy via OCR, validated by the
    route-total invariant (current+remaining ~= total); None on an unreadable /
    invalid frame. Paces itself and runs until interrupted (Ctrl+C)."""
    import mss
    import numpy as np
    import hud_reader
    total_m, tol_m = TOTAL_KM * 1000.0, 25.0
    cfg = hud_reader.load_config(config_path)
    cur, rem = cfg["current_distance"], cfg["remaining_distance"]
    left, top, w, h = (int(v) for v in region_str.split(","))
    region = {"left": left, "top": top, "width": w, "height": h}
    sct = mss.mss()

    def read(box):
        x1, y1, x2, y2 = box
        g = {"left": region["left"] + x1, "top": region["top"] + y1,
             "width": x2 - x1, "height": y2 - y1}
        s = np.array(sct.grab(g))[:, :, :3]
        hh, ww = s.shape[:2]
        r = hud_reader.read_region(s, (0, 0, ww, hh), "unit_value", None, 7)
        if not isinstance(r, tuple):
            return None
        n, u = r
        return n * 1000.0 if isinstance(u, str) and u.lower().startswith("km") else float(n)

    while True:
        c, r = read(cur["box"]), read(rem["box"])
        yield None if (c is None or r is None or abs(c + r - total_m) > tol_m) else c / 1000.0
        time.sleep(period)


# --- the ride ----------------------------------------------------------------

def ride_session(store_path, positions, voices, captions, *, speed=1.0, live=False,
                 voices_dir=VOICES_DIR):
    """Hear the demo_voices clips AND everything in the store as they're crossed.

    Plays ANY kind="audio" artifact -- the demo_voices clips and voice clips left
    by demo_leave_message.py (shared store). Non-audio artifacts (text trinkets)
    are announced. `positions` is a finite list (synthetic/stream) OR a live
    generator that yields None on an unreadable frame and runs until Ctrl+C.
    """
    store = ArtifactStore(store_path)          # only the file carries data across
    recorded = store.artifacts_for(ROUTE_ID)
    disc = ArtifactDiscoverer(voices + recorded, trigger_radius_km=TRIGGER_RADIUS_KM)

    bed = AudioBed()
    print("=== Ride: hear the voices left along the route ===")
    print(f"  {len(voices)} demo voice(s) from {voices_dir}")
    print(f"  {len(recorded)} recorded artifact(s) from {store_path}")
    for a in sorted(voices + recorded, key=lambda a: a.position_km):
        print(f"    @ {a.position_km*1000:6.0f} m  {a.author:8s} {os.path.basename(a.payload)}")
    print(f"  audio {'ON' if bed.available else 'OFF (headless -- trace only)'}"
          + ("  |  riding LIVE -- Ctrl+C to stop" if live else "") + "\n")
    if not voices and not recorded:
        print(f"  (nothing to play -- add clips to {voices_dir} or record some first)\n")

    playing = {}   # artifact.id -> anchor_km, so we know when we've ridden past
    dt = 0.15 / max(speed, 0.01)
    try:
        for km in positions:
            for a in disc.advance(km):        # advance() safely ignores km is None
                if a.kind != "audio":
                    print(f"  [{km:5.3f} km] FOUND {a.author}'s trinket: \"{a.payload}\"")
                    continue
                if not os.path.exists(a.payload):
                    print(f"  [{km:5.3f} km] (missing clip {os.path.basename(a.payload)})")
                    continue
                bed.play(a.id, a.payload, fade_ms=FADE_IN_MS)
                playing[a.id] = a.position_km
                layered = " (LAYERED)" if len(playing) > 1 else ""
                cap = captions.get(a.payload, os.path.basename(a.payload))
                print(f"  [{km:5.3f} km] HEAR {a.author}'s memory{layered}: \"{cap}\"")
            if km is not None:
                for cid, anchor in list(playing.items()):
                    if km > anchor + PASS_KM:
                        bed.fade_out(cid, FADE_OUT_MS)
                        del playing[cid]
                        print(f"  [{km:5.3f} km]  ...fading out (rode past)")
            bed.update()
            if not live:
                time.sleep(dt)
    except KeyboardInterrupt:
        pass

    # let any in-flight fade-outs finish before we tear down
    end = time.monotonic() + (FADE_OUT_MS / 1000.0)
    while time.monotonic() < end:
        bed.update()
        time.sleep(0.05)
    bed.close()
    print("\n  ride over.")


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--store", default=os.path.join(_PROJ, "output", "audio_memories_store.json"))
    ap.add_argument("--voices", default=VOICES_DIR,
                    help="folder of pre-recorded voice clips (default: demo_voices/)")
    ap.add_argument("--stream", default=None,
                    help="stream_hud JSONL for real OCR positions (default: synthetic ride)")
    ap.add_argument("--live", action="store_true", help="read live position off Rouvy via OCR")
    ap.add_argument("--region", default="1920,0,1920,1080")
    ap.add_argument("--config", default=os.path.join(_PROJ, "configs", "campus_bike_1.json"))
    ap.add_argument("--speed", type=float, default=1.0, help="playback speed (non-live)")
    ap.add_argument("--reset", action="store_true",
                    help="wipe the RECORDED store first (demo_voices/ files are untouched)")
    args = ap.parse_args()

    if args.reset and os.path.exists(args.store):
        os.remove(args.store)

    voices, captions = load_demo_voices(args.voices)

    if args.live:
        positions, live = live_positions(args.region, args.config), True
    elif args.stream:
        positions = list(stream_positions(args.stream))
        if not positions:
            raise SystemExit(f"No readable current_distance in {args.stream}.")
        live = False
    else:
        positions, live = list(synthetic_positions()), False

    ride_session(args.store, positions, voices, captions, speed=args.speed, live=live,
                 voices_dir=args.voices)


if __name__ == "__main__":
    main()
