"""
gaze_audio_messages_demo.py -- ONE live script for the eye-tracking study:
riders HEAR human voice messages along the route and can RECORD their own.

  * HEAR    -- clips from demo_voices/ (file name = route position; see
               demo_voices/README.md) fade in as the rider reaches each spot
               and out once past. ONLY demo_voices/ clips are played: the
               rider's own recordings (and other riders' recordings) are
               saved for analysis but never played back.
  * RECORD  -- gamepad A / keyboard SPACE records a --seconds clip pinned to the
               current position (saved to output/messages/ + the --store).

What this script adds over the two separate demos:
  1. MIC BLEED: pressing record fades out every playing clip, and any clip
     reached DURING the recording is held; when the recording ends (ffmpeg has
     exited, not just the countdown) a held clip plays if the rider is still
     within PASS_KM of its spot, otherwise it's skipped (and logged).
  2. PER-LAP REPLAY: crossing the start line again (valid distance jumps from
     the end of the route back to ~0) starts a new lap -- demo_voices/ is
     re-read and every clip can play again. A PRERIDE (new ride) does the same.
  6. PAUSE / IDLE: the audio tour's OCR state machine (PRERIDE/RIDING/PAUSED/
     IDLE). Clips only start while RIDING; pausing or leaving the ride fades
     out whatever is playing (a clip reached-but-unplayed is NOT lost by a
     pause -- it plays on resume if still in range). Recording is RIDING-only.
  7. EVENT LOG: every state change, lap, clip start/end/stop/hold/skip and
     recording start/end goes to a CSV in output/gaze_logs/ with a Unix
     timestamp (ms) -- the column to line up with the eye tracker's clock.

Deliberately NOT here (need study-design input -- see
docs/gaze-study-audio-messages.md): any on-screen visual when a clip plays
(item 5), and prompted-vs-free recording (item 8). Recording is free (any time
while riding); playback is audio-only. The only overlay is the status chip and
the red "RECORDING Ns" countdown.

Controls: A (button 0) / SPACE = record; ESC (global, works with Rouvy focused)
or Q = quit (waits for any recording still writing).

On the rig:
    python gaze_audio_messages_demo.py --live --region 1920,0,1920,1080 \
        --device "Microphone Array (2- Realtek(R) Audio)" --rider P01
At a desk (synthetic ride, laps every ~35 s, keyboard):
    python gaze_audio_messages_demo.py --simulate
"""

import argparse
import csv
import os
import sys
import time
from datetime import datetime

_PROJ = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_PROJ, "route_artifacts_poc"))

import input_trigger as it  # noqa: E402
import record_audio  # noqa: E402
from audio_bed import AudioBed  # noqa: E402
from demo_audio_memories import (  # noqa: E402
    FADE_IN_MS, FADE_OUT_MS, PASS_KM, TRIGGER_RADIUS_KM, VOICES_DIR, load_demo_voices)
from demo_leave_message import (  # noqa: E402
    IDLE, PAUSED, PRERIDE, RIDING, TOTAL_M, Indicator, LivePosition, SimPosition,
    RIDING_STICKY_SECS, STATE_EVERY_S, _esc_pressed, accept_action, next_state, probe_for)
from route_artifacts import ArtifactDiscoverer, ArtifactStore  # noqa: E402

ROUTE_ID = "campus-loop"
TOTAL_KM = TOTAL_M / 1000.0
MSG_DIR = os.path.join(_PROJ, "output", "messages")
LOG_DIR = os.path.join(_PROJ, "output", "gaze_logs")

LAP_EDGE_KM = 0.15      # a new lap lands within this of the start ...
LAP_DROP_KM = 0.30      # ... after a backwards jump at least this big


# --- pure logic (unit-tested in test_gaze_audio_messages.py) -----------------

def is_new_lap(prev_km, km, *, edge_km=LAP_EDGE_KM, drop_km=LAP_DROP_KM):
    """Two VALID reads: did the rider wrap back to the start? Covers both a
    normal lap (end -> ~0) and Rouvy restarting the route mid-ride."""
    if prev_km is None or km is None:
        return False
    return km <= edge_km and (prev_km - km) >= drop_km


class ClipScheduler:
    """Decides what the audio should do; plays nothing itself.

    Every method returns a list of (command, artifact, reason) tuples:
        ("play", a, "")                 start this clip
        ("stop", a, reason)             fade it out; reason = passed / recording
                                        / paused / lap
        ("hold", a, "recording")        reached while recording -- deferred
        ("skip", a, "passed while recording")
        ("end",  a, "")                 it finished on its own
    The caller executes them on the AudioBed and logs them, so this class is
    testable with no audio device.
    """

    def __init__(self, voices, *, radius_km=TRIGGER_RADIUS_KM, pass_km=PASS_KM):
        self.radius, self.pass_km = radius_km, pass_km
        self.playing = {}   # artifact id -> artifact
        self.held = []
        self.disc = ArtifactDiscoverer(list(voices), trigger_radius_km=radius_km)

    def reset(self, voices, reason="lap"):
        """New lap / new ride: stop what's playing, re-arm every clip."""
        out = self._stop_all(reason)
        self.held = []
        self.disc = ArtifactDiscoverer(list(voices), trigger_radius_km=self.radius)
        return out

    def _stop_all(self, reason):
        out = [("stop", a, reason) for a in self.playing.values()]
        self.playing = {}
        return out

    def _start(self, a):
        self.playing[a.id] = a
        return [("play", a, "")]

    def tick(self, km, *, riding, recording):
        if not riding:
            return self._stop_all("paused")   # held clips survive a pause
        if km is None:
            return []
        out = []
        for a in self.disc.advance(km):
            if recording:
                self.held.append(a)
                out.append(("hold", a, "recording"))
            else:
                out += self._start(a)
        if not recording and self.held:
            for a in self.held:
                if km <= a.position_km + self.pass_km:
                    out += self._start(a)
                else:
                    out.append(("skip", a, "passed while recording"))
            self.held = []
        for aid, a in list(self.playing.items()):
            if km > a.position_km + self.pass_km:
                del self.playing[aid]
                out.append(("stop", a, "passed"))
        return out

    def start_recording(self):
        return self._stop_all("recording")

    def finished(self, clip_id):
        a = self.playing.pop(clip_id, None)
        return [("end", a, "")] if a else []


# --- event log ---------------------------------------------------------------

class EventLog:
    """CSV, one row per event, flushed immediately (a crash keeps the data).
    unix_time is the sync column for the eye tracker."""
    FIELDS = ["unix_time", "iso_time", "t_s", "event", "state", "lap",
              "position_m", "clip", "author", "detail"]

    def __init__(self, path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self.path = path
        self._f = open(path, "w", newline="", encoding="utf-8")
        self._w = csv.DictWriter(self._f, fieldnames=self.FIELDS)
        self._w.writeheader()
        self._t0 = time.monotonic()

    def log(self, event, *, state, lap, km, clip="", author="", detail=""):
        now = time.time()
        self._w.writerow({
            "unix_time": f"{now:.3f}",
            "iso_time": datetime.fromtimestamp(now).isoformat(timespec="milliseconds"),
            "t_s": f"{time.monotonic() - self._t0:.3f}",
            "event": event, "state": state or "", "lap": lap,
            "position_m": "" if km is None else f"{km * 1000:.0f}",
            "clip": clip, "author": author, "detail": detail,
        })
        self._f.flush()

    def close(self):
        self._f.close()


# --- main loop ---------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--simulate", action="store_true", help="synthetic ride (no bike)")
    ap.add_argument("--live", action="store_true", help="read position + state off Rouvy")
    ap.add_argument("--region", default="1920,0,1920,1080")
    ap.add_argument("--config", default=os.path.join(_PROJ, "configs", "campus_bike_1.json"))
    ap.add_argument("--rider", default="rider", help="participant id (file names + log)")
    ap.add_argument("--device", default=None, help="mic dshow name (default: first found)")
    ap.add_argument("--seconds", type=float, default=5.0, help="recording length")
    ap.add_argument("--voices", default=VOICES_DIR, help="folder of clips to play")
    ap.add_argument("--store", default=os.path.join(_PROJ, "output", "gaze_recordings_store.json"),
                    help="where recordings are indexed (never played back here)")
    ap.add_argument("--log-dir", default=LOG_DIR)
    ap.add_argument("--no-overlay", action="store_true")
    ap.add_argument("--sim-step", type=float, default=0.02, help="km per 0.5 s (--simulate)")
    args = ap.parse_args()
    if not (args.simulate or args.live):
        args.simulate = True

    device = args.device
    if device is None and not args.simulate:
        found = record_audio.list_input_devices()
        device = found[0] if found else None
    print(f"[mic] {device!r}" if device else "[mic] none -- recordings will be silent markers only")

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log = EventLog(os.path.join(args.log_dir, f"gaze_{args.rider}_{stamp}.csv"))
    pos = SimPosition(args.sim_step) if args.simulate else LivePosition(args.region, args.config)
    store = ArtifactStore(args.store)
    trig = it.InputTrigger(window_title="gaze study  (SPACE/A = record, ESC/Q = quit)")
    ind = Indicator(args.region, enabled=args.live and not args.no_overlay)
    bed = AudioBed()

    voices, captions = load_demo_voices(args.voices)
    sched = ClipScheduler(voices)
    print(f"[voices] {len(voices)} clip(s) from {args.voices}")
    for a in voices:
        print(f"    @ {a.position_km*1000:5.0f} m  {a.author:8s} {os.path.basename(a.payload)}")
    print(f"[audio] {'ON' if bed.available else 'OFF (no device)'}   "
          f"[input] {trig.gamepad_names or 'keyboard only'}")
    print(f"[log] {log.path}\n")

    state = RIDING if args.simulate else None
    lap = 1
    cur_km = None          # position for pinning/playback (cleared off-ride)
    prev_valid_km = None   # last valid read, never cleared -- for lap detection
    last_read = last_state = last_valid = -999.0
    rec_until, rec_proc, rec_path = None, None, None
    shown_left = None
    pending = []
    seq = 0

    def ev(event, a=None, detail=""):
        log.log(event, state=state, lap=lap, km=cur_km,
                clip=os.path.basename(a.payload) if a else "",
                author=a.author if a else "", detail=detail)

    def run(cmds):
        for cmd, a, reason in cmds:
            if cmd == "play":
                ok = bed.play(a.id, a.payload, fade_ms=FADE_IN_MS)
                ev("clip_start", a, "" if ok or not bed.available else "failed to load")
                print(f"\n[hear] {a.author} @ {a.position_km*1000:.0f} m: "
                      f"\"{captions.get(a.payload, '')}\"")
            elif cmd == "stop":
                bed.fade_out(a.id, FADE_OUT_MS)
                ev("clip_stop", a, reason)
            elif cmd == "hold":
                ev("clip_hold", a, reason)
            elif cmd == "skip":
                ev("clip_skip", a, reason)
                print(f"\n[skip] {a.author}'s clip -- rode past it while recording")
            elif cmd == "end":
                ev("clip_end", a)

    ev("session_start", detail=f"rider={args.rider} mode={'sim' if args.simulate else 'live'} "
                               f"voices={len(voices)} audio={bed.available}")
    try:
        while True:
            now = time.monotonic()
            if _esc_pressed():
                break

            # --- position (0.5 s) + lap detection ---
            if now - last_read >= 0.5:
                last_read = now
                km = pos.read()
                if km is not None:
                    if is_new_lap(prev_valid_km, km):
                        lap += 1
                        voices, captions = load_demo_voices(args.voices)
                        run(sched.reset(voices, "lap"))
                        cur_km = km
                        ev("lap_start", detail=f"from {prev_valid_km*1000:.0f} m")
                        print(f"\n[lap] lap {lap} -- clips re-armed ({len(voices)})")
                    prev_valid_km, cur_km, last_valid = km, km, now
                print(f"\rpos={'—' if cur_km is None else f'{cur_km*1000:.0f} m'}  "
                      f"state={state}  lap={lap}   ", end="", flush=True)

            # --- ride state (live only) ---
            if not args.simulate and now - last_state >= STATE_EVERY_S:
                last_state = now
                new = next_state(state, seen=pos.screen_shows(probe_for(state)),
                                 riding_signal=(now - last_valid) < RIDING_STICKY_SECS)
                if new != state:
                    state = new
                    if state == PRERIDE:          # new ride: re-arm everything
                        lap = 1
                        voices, captions = load_demo_voices(args.voices)
                        run(sched.reset(voices, "new ride"))
                    if state in (PRERIDE, IDLE):
                        cur_km = None
                    ind.status(state)
                    ev("state", detail=state)
                    print(f"\nstate -> {state}")

            # --- recording lock: countdown AND ffmpeg actually finished ---
            proc_alive = rec_proc is not None and rec_proc.poll() is None
            recording = (rec_until is not None and now < rec_until) or proc_alive
            left = int(rec_until - now) + 1 if rec_until is not None and now < rec_until else None
            if left != shown_left:
                ind.recording(left)
                shown_left = left
            if rec_until is not None and not recording:
                size = os.path.getsize(rec_path) if rec_path and os.path.exists(rec_path) else 0
                ev("record_end", detail=f"{os.path.basename(rec_path)} {size} bytes")
                print(f"\n[rec] done ({size} bytes)")
                rec_until, rec_proc, rec_path = None, None, None

            # --- playback ---
            run(sched.tick(cur_km, riding=(state == RIDING), recording=recording))
            if bed.available:
                for aid in list(sched.playing):
                    if not bed.is_playing(aid):
                        run(sched.finished(aid))
            bed.update()

            # --- input ---
            for action in trig.poll():
                if action == it.QUIT:
                    raise KeyboardInterrupt
                if action != it.LEAVE_MESSAGE:
                    continue                      # trinkets aren't part of the study
                ok, why = accept_action(action, state=state, cur_km=cur_km,
                                        recording=recording)
                if not ok:
                    ev("record_refused", detail=why)
                    print(f"\n[skip] record: {why}")
                    continue
                run(sched.start_recording())      # duck playback before the mic opens
                seq += 1
                stem = f"{ROUTE_ID}_{args.rider}_{int(time.time())}_{seq}"
                rec_path = os.path.join(MSG_DIR, stem + ".mp3")
                rec_proc = None
                if device is not None:
                    rec_proc = record_audio.record(device, rec_path, args.seconds,
                                                   log_path=os.path.join(MSG_DIR, stem + ".log"))
                    if rec_proc:
                        pending.append((rec_proc, rec_path))
                rec_until = now + args.seconds
                store.drop(ROUTE_ID, cur_km, rec_path, author=args.rider, kind="audio")
                store.save()
                ev("record_start", detail=f"{os.path.basename(rec_path)} "
                                          f"{'mic' if rec_proc else 'NO MIC'}")
                print(f"\n[rec] recording {args.seconds:.0f}s @ {cur_km*1000:.0f} m")

            ind.update()
            time.sleep(0.02)
    except KeyboardInterrupt:
        pass
    finally:
        ev("session_end")
        bed.close()
        trig.close()
        ind.close()
        if pending:
            print(f"\nfinishing {len(pending)} recording(s)…")
            for proc, path in pending:
                try:
                    proc.wait(timeout=args.seconds + 10)
                except Exception:
                    proc.kill()
                size = os.path.getsize(path) if os.path.exists(path) else 0
                print(f"  {'OK ' if size else 'FAIL'} {os.path.basename(path)} ({size} bytes)")
        log.close()
        print(f"\nlog: {log.path}")


if __name__ == "__main__":
    main()
