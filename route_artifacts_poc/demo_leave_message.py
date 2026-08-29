"""
demo_leave_message.py  --  the LEAVE half of the audio-memory loop.

Closes the loop started by demo_audio_memories.py (the HEAR half). While riding,
the rider presses a control (gamepad on the rig, keyboard at a desk) and:

  * "leave_message"  -> record a short voice clip from the mic and pin it, as a
    kind="audio" artifact, to the CURRENT route position;
  * "option_1/2/3"   -> drop a preset "trinket" (a light text artifact) at the
    current position -- the 3-choice variant, no recording.

Next session, demo_audio_memories.py (same --store, same route) plays these back
as the next rider crosses each spot. That's the whole feature: press -> speak ->
persist at a place -> a later rider hears it there.

Two things are deliberately decoupled so each was buildable/testable off-rig:
  * INPUT comes through input_trigger (source-swappable: gamepad or keyboard) --
    so this runs at a desk with the keyboard today and on the rig with the
    borrowed gamepad tomorrow, unchanged.
  * RECORDING is a background ffmpeg capture (record_audio); if the mic/ffmpeg
    isn't there, the artifact is still dropped (silent) so the loop logic is
    exercised regardless.

POSITION is either a synthetic ramp (--simulate, no bike) or the live OCR read
of current_distance, validated by the route-total invariant (--live).

Desk smoke test (no bike, keyboard):
    python demo_leave_message.py --simulate
    #   SPACE = leave a voice message, 1/2/3 = drop a trinket, Q = quit
    python demo_audio_memories.py            # hear them back

On the rig (gamepad + real ride):
    python demo_leave_message.py --live --region 1920,0,1920,1080 --device "<mic>"
"""

import argparse
import os
import sys
import time

_PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _PROJ)

import input_trigger as it  # noqa: E402
import record_audio  # noqa: E402
from route_artifacts import ArtifactStore  # noqa: E402

ROUTE_ID = "campus-loop"
TOTAL_M = 1344.0
TOL_M = 25.0
MSG_DIR = os.path.join(_PROJ, "output", "messages")

TRINKETS = {
    it.OPTION_1: "left a Paws plushie here",
    it.OPTION_2: "left an NU poster here",
    it.OPTION_3: "left a shout-out here",
}


def _to_m(reading):
    if not isinstance(reading, tuple):
        return None
    num, unit = reading
    if isinstance(unit, str) and unit.strip().lower().startswith("km"):
        return num * 1000.0
    return float(num)


class SimPosition:
    """A synthetic ride: advances a bit each read, wraps at the route end."""
    def __init__(self, step_km=0.02):
        self.km = 0.0
        self.step = step_km

    def read(self):
        self.km = round(self.km + self.step, 3)
        if self.km > TOTAL_M / 1000.0:
            self.km = 0.0
        return self.km


class LivePosition:
    """Live OCR of current_distance (km), validated by current+remaining≈total."""
    def __init__(self, region, config):
        import mss
        import hud_reader
        self._np = __import__("numpy")
        self._hud = hud_reader
        self.sct = mss.mss()
        cfg = hud_reader.load_config(config)
        self.cur, self.rem = cfg["current_distance"], cfg["remaining_distance"]
        left, top, w, h = (int(v) for v in region.split(","))
        self.region = {"left": left, "top": top, "width": w, "height": h}

    def _grab(self, box):
        x1, y1, x2, y2 = box
        g = {"left": self.region["left"] + x1, "top": self.region["top"] + y1,
             "width": x2 - x1, "height": y2 - y1}
        shot = self._np.array(self.sct.grab(g))[:, :, :3]
        hh, ww = shot.shape[:2]
        return self._hud.read_region(shot, (0, 0, ww, hh), "unit_value",
                                     None, 7)

    def read(self):
        c = _to_m(self._grab(self.cur["box"]))
        r = _to_m(self._grab(self.rem["box"]))
        if c is None or r is None or abs(c + r - TOTAL_M) > TOL_M:
            return None  # unreadable / failed the invariant -> no position
        return c / 1000.0


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--store", default=os.path.join(_PROJ, "output", "audio_memories_store.json"))
    ap.add_argument("--rider", default="rider")
    ap.add_argument("--simulate", action="store_true", help="synthetic ride (no bike)")
    ap.add_argument("--live", action="store_true", help="read position off Rouvy via OCR")
    ap.add_argument("--region", default="1920,0,1920,1080")
    ap.add_argument("--config", default=os.path.join(_PROJ, "configs", "campus_bike_1.json"))
    ap.add_argument("--device", default=None, help="mic dshow name (default: first found)")
    ap.add_argument("--seconds", type=float, default=5.0, help="voice clip length")
    ap.add_argument("--reset", action="store_true", help="wipe the store first (fresh session)")
    args = ap.parse_args()

    if not (args.simulate or args.live):
        args.simulate = True  # default to the safe desk mode
    if args.reset and os.path.exists(args.store):
        os.remove(args.store)

    device = args.device
    if device is None and not args.simulate:
        found = record_audio.list_input_devices()
        device = found[0] if found else None
        print(f"[mic] using {device!r}" if device else "[mic] none found -- clips will be silent/skipped")

    pos = SimPosition() if args.simulate else LivePosition(args.region, args.config)
    store = ArtifactStore(args.store)
    trig = it.InputTrigger(window_title="leave-message  (SPACE=voice  1/2/3=trinket  Q=quit)")
    if trig.gamepad_names:
        print(f"[input] gamepad(s): {trig.gamepad_names}")
    print(f"[input] keyboard fallback active. Controls: SPACE / 1 / 2 / 3 / Q")
    print(f"[store] {args.store}  route={ROUTE_ID}\n")

    seq = 0
    last_read = 0.0
    cur_km = None
    pending = []   # (proc, path) recordings still finishing in the background
    try:
        while True:
            now = time.monotonic()
            if now - last_read >= 0.5:
                last_read = now
                km = pos.read()
                if km is not None:
                    cur_km = km
                print(f"\rpos={cur_km if cur_km is None else round(cur_km,3)} km   ",
                      end="", flush=True)

            for action in trig.poll():
                if action == it.QUIT:
                    raise KeyboardInterrupt
                if cur_km is None:
                    print("\n[skip] no valid position yet -- can't pin here.")
                    continue
                if action == it.LEAVE_MESSAGE:
                    seq += 1
                    # timestamp keeps filenames unique ACROSS runs (a per-run
                    # counter collided and overwrote earlier clips).
                    stem = f"{ROUTE_ID}_{args.rider}_{int(time.time())}_{seq}"
                    path = os.path.join(MSG_DIR, stem + ".mp3")
                    proc = None
                    if device is not None:
                        proc = record_audio.record(device, path, args.seconds,
                                                   log_path=os.path.join(MSG_DIR, stem + ".log"))
                        if proc:
                            pending.append((proc, path))
                    a = store.drop(ROUTE_ID, cur_km, path, author=args.rider, kind="audio")
                    store.save()
                    tag = f"recording {args.seconds:.0f}s…" if proc else "(no mic -- artifact only)"
                    print(f"\n[leave] voice memory @ {a.position_km:.3f} km {tag} -> {os.path.basename(path)}")
                elif action in TRINKETS:
                    a = store.drop(ROUTE_ID, cur_km, TRINKETS[action],
                                   author=args.rider, kind="text")
                    store.save()
                    print(f"\n[leave] trinket @ {a.position_km:.3f} km: \"{TRINKETS[action]}\"")
            time.sleep(0.02)
    except KeyboardInterrupt:
        pass
    finally:
        trig.close()
        # CRUCIAL: wait for background recordings to finish writing, or the OS
        # kills ffmpeg on exit and the files never materialise (empty folder).
        if pending:
            print(f"\nfinishing {len(pending)} recording(s)…")
            for proc, path in pending:
                try:
                    proc.wait(timeout=args.seconds + 10)
                except Exception:
                    proc.kill()
                ok = os.path.exists(path) and os.path.getsize(path) > 0
                size = os.path.getsize(path) if os.path.exists(path) else 0
                print(f"  {'OK ' if ok else 'FAIL'} {os.path.basename(path)} ({size} bytes)"
                      + ("" if ok else " -- see the .log next to it"))
        n = len(store.artifacts_for(ROUTE_ID))
        print(f"\ndone. {n} artifact(s) on '{ROUTE_ID}'. "
              f"Run demo_audio_memories.py (same --store) next session to hear them.")


if __name__ == "__main__":
    main()
