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

The persistence claim is DEMONSTRATED, not asserted: session 2 opens a brand-new
store from the same file on disk, so the only way Alice's memories reach Bob is
that file. As Bob crosses each spot the clip fades IN; once he rides past, it
fades OUT. Two memories placed close together overlap -> you hear them LAYERED,
which is exactly what the single music-bed API could not do.

Location-tied vs rider-tied: this demo is location-tied (memories pinned to the
route). A ghost-rider/bot is the SAME engine with a MOVING anchor instead of a
fixed one -- that's the next POC, not a rewrite.

Runs headless: with no audio device AudioBed no-ops and you still see the full
discovery trace (persistence + triggering proven). On a real machine you HEAR
it -- which is what the live rig test is for.

The sample clips are auto-generated PLACEHOLDER tones (distinct pitches so an
overlap is an audible chord). Swap them for real rider recordings by dropping
.wav/.ogg files in and pointing --clips at them.

Usage:
    python demo_audio_memories.py                 # synthetic ride, campus length
    python demo_audio_memories.py --speed 4       # 4x faster (less waiting)
    python demo_audio_memories.py --stream ../run.jsonl   # real OCR positions
"""

import argparse
import math
import os
import struct
import sys
import time
import wave

# audio_bed lives in the project root (this POC is a subfolder).
_PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _PROJ)

from audio_bed import AudioBed  # noqa: E402
from route_artifacts import ArtifactDiscoverer, ArtifactStore  # noqa: E402

ROUTE_ID = "campus-loop"
TOTAL_KM = 1.344                 # campus route total (see CLAUDE.md invariant)
SAMPLE_DIR = os.path.join(_PROJ, "output", "sample_memories")

# Where each rider left an audio memory (km) and the placeholder pitch for it.
# 0.62 and 0.66 sit within a fade window of each other on purpose -> they LAYER.
MEMORIES = [
    ("alice", 0.30, "By the library steps: 'good luck on finals!'", 523),
    ("alice", 0.62, "At the crossing: 'watch the T tracks here'",   659),
    ("bob",   0.66, "Bob: 'race you to the top'",                    784),
    ("carol", 1.05, "Carol: 'almost home -- best view is left'",    440),
]

TRIGGER_RADIUS_KM = 0.03   # start the memory a touch BEFORE its spot (a lure)
PASS_KM = 0.10             # fade the memory out once this far past its spot
FADE_IN_MS = 700
FADE_OUT_MS = 1200


def _write_tone(path, secs=4.0, freq=440, rate=44100):
    n = int(secs * rate)
    with wave.open(path, "w") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        # gentle attack/decay so a placeholder isn't a harsh square click
        w.writeframes(b"".join(
            struct.pack("<h", int(32767 * 0.18
                                  * math.sin(2 * math.pi * freq * i / rate)
                                  * min(1.0, i / (rate * 0.05),
                                        (n - i) / (rate * 0.05))))
            for i in range(n)))


def ensure_sample_clips():
    """Create the placeholder tones if they aren't there yet; return {author: path}."""
    os.makedirs(SAMPLE_DIR, exist_ok=True)
    paths = {}
    for author, _pos, _text, freq in MEMORIES:
        p = os.path.join(SAMPLE_DIR, f"memory_{author}_{freq}.wav")
        if not os.path.exists(p):
            _write_tone(p, freq=freq)
        paths[(author, freq)] = p
    return paths


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


def drop_session(store_path, clip_paths):
    """Session 1: riders leave their audio memories, then the store is saved."""
    store = ArtifactStore(store_path)
    print("=== Session 1: riders leave audio memories ===")
    if store.artifacts_for(ROUTE_ID):
        # already dropped on an earlier run -> don't duplicate; this is the
        # persistence point (the memories are still on disk from last time).
        print("  (memories already on the route from a previous run -- kept)\n")
        return
    for author, pos, text, freq in MEMORIES:
        a = store.drop(ROUTE_ID, pos, clip_paths[(author, freq)],
                       author=author, kind="audio")
        print(f"  ~drop~  {author:5s} @ {a.position_km:4.2f} km  \"{text}\"")
    store.save()
    print(f"  saved -> {store_path}\n")


def ride_session(store_path, positions, captions, *, speed=1.0, live=False):
    """Session 2: a FRESH store from disk; hear the memories as they're crossed.

    Plays ANY kind="audio" artifact on the route -- the scripted ones AND voice
    clips left by demo_leave_message.py -- so the two demos interoperate through
    the shared store. Non-audio artifacts (e.g. text trinkets) are announced.
    `positions` is a finite list (synthetic/stream) OR a live generator that
    yields None on an unreadable frame and runs until Ctrl+C.
    """
    store = ArtifactStore(store_path)          # only the file carries data across
    existing = store.artifacts_for(ROUTE_ID)
    disc = ArtifactDiscoverer(existing, trigger_radius_km=TRIGGER_RADIUS_KM)

    bed = AudioBed()
    print("=== Session 2: a new rider hears the past riders' memories ===")
    print(f"  {len(existing)} memory(ies) on the route; audio "
          f"{'ON' if bed.available else 'OFF (headless -- trace only)'}"
          + ("  |  riding LIVE -- Ctrl+C to stop" if live else "") + "\n")

    playing = {}   # artifact.id -> anchor_km, so we know when we've ridden past
    dt = 0.15 / max(speed, 0.01)
    try:
        for km in positions:
            for a in disc.advance(km):        # advance() safely ignores km is None
                if a.kind != "audio":
                    print(f"  [{km:5.3f} km] FOUND {a.author}'s trinket: \"{a.payload}\"")
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
    print("\n  ride over. (re-run without --reset: memories still there)")


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--store", default=os.path.join(_PROJ, "output", "audio_memories_store.json"))
    ap.add_argument("--stream", default=None,
                    help="stream_hud JSONL for real OCR positions (default: synthetic ride)")
    ap.add_argument("--live", action="store_true", help="read live position off Rouvy via OCR")
    ap.add_argument("--region", default="1920,0,1920,1080")
    ap.add_argument("--config", default=os.path.join(_PROJ, "configs", "campus_bike_1.json"))
    ap.add_argument("--speed", type=float, default=1.0, help="playback speed (non-live)")
    ap.add_argument("--reset", action="store_true", help="wipe the store for a clean run")
    args = ap.parse_args()

    if args.reset and os.path.exists(args.store):
        os.remove(args.store)

    clip_paths = ensure_sample_clips()
    # captions for THIS demo's scripted drops, keyed by CLIP PATH so they can't
    # collide with artifacts left by another demo; anything else -> its filename.
    captions = {clip_paths[(author, freq)]: text
                for author, _pos, text, freq in MEMORIES}

    drop_session(args.store, clip_paths)

    if args.live:
        positions, live = live_positions(args.region, args.config), True
    elif args.stream:
        positions = list(stream_positions(args.stream))
        if not positions:
            raise SystemExit(f"No readable current_distance in {args.stream}.")
        live = False
    else:
        positions, live = list(synthetic_positions()), False

    ride_session(args.store, positions, captions, speed=args.speed, live=live)


if __name__ == "__main__":
    main()
