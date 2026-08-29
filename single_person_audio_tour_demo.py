"""
single_person_audio_tour_demo.py -- LIVE, screen-state-aware overlay over Rouvy.

The single-person AUDIO TOUR test demo: one rider, a companion overlay + a
layered audio experience (background bed, Emma, Ruggles, Curry) driven live off
the Rouvy HUD. (Was demo_overlay_live.py.)

Drives the companion overlay from what Rouvy is ACTUALLY showing -- detected by
OCR of distinctive on-screen text (calibrated live) plus the live distance read:

  PRERIDE  -- "Start over or resume ride?" dialog up  -> "TOUR READY TO BEGIN"
  RIDING   -- on the route (distance HUD present)     -> "COMPANION TOUR ACTIVE",
              welcome ONCE, then landmark alerts; Emma fires at ~87 m and while
              her bubble is up NOTHING else shows
  PAUSED   -- the pause menu's "CONTINUE RIDE" button is up (NOT just 0 W --
              Rouvy inertia keeps rolling) -> "PAUSED", alerts frozen
  IDLE     -- Rouvy's main screen / anything else -> overlay fully blank
              (fixes: main screen used to still say "tour active")

Distance is VALIDATED with the route-total invariant: current + remaining must
sum to ~TOTAL_M (1344 m). A frame that fails is ignored, so a current-distance
misread (e.g. 33 read as 88) can't false-fire Emma. RIDING is itself detected
by that invariant holding, so the main screen (no ride HUD) falls to IDLE.

Alerts: "Landmark ahead: Ruggles" periodically for the first 500 m, then a
sporadic "Photo spot".

Audio (audio_bed): 4 background loops layer + fade at random as a QUIET bed all
ride; a "Ruggles approaching" clip plays at 400 m (banner -> "Landmark ahead:
Ruggles (100m)") and "Ruggles unlocked" at 500 m; retro arcade music fades IN
at 675 m with a "Curry Student Center: After Hours concert" sign and OUT at
720 m. Re-armed on each new ride; with --retrigger, each beat also re-arms
whenever you loop back below its trigger, so the fades replay every lap.

Run with Rouvy on the external monitor (windowed/borderless):
    python single_person_audio_tour_demo.py --region 1920,0,1920,1080 --delay 5
"""

import argparse
import ctypes
import glob
import os
import random
import time

import mss
import numpy as np
import pytesseract

import hud_reader
from overlay import RideOverlay

from audio_bed import AudioBed

WELCOME = "Welcome to your campus companion tour!"
EMMA = ("I'm Emma, your tour guide! We're taking a short lap around campus. "
        "We're just crossing the Northeastern Green Line T stop now.")

TOTAL_M = 1344.0     # campus route total (current + remaining), measured off the HUD
TOL_M = 25.0         # invariant tolerance (absorbs m<->km rounding)

# screen-state detection regions (monitor-relative), calibrated live:
PRERIDE_BOX = (760, 420, 1160, 480)    # "Start over or resume ride?"
PAUSE_BOX = (1480, 980, 1900, 1045)    # the pause menu's "CONTINUE RIDE" button

# --- experience audio (data/prototype-demo) ---
EXP_DIR = os.path.join("data", "prototype-demo")
BG_CLIPS = [os.path.join(EXP_DIR, f"Background sound {i}.mp3") for i in (1, 2, 3, 4)]
RUGGLES_APPROACH = os.path.join(EXP_DIR, "Ruggles Station - approaching.mp3")
RUGGLES_UNLOCKED = os.path.join(EXP_DIR, "Ruggles Station - unlocked and continued story.mp3")

RUGGLES_APPROACH_M = 400.0   # play "approaching" + show "Ruggles (100m)" banner
RUGGLES_UNLOCK_M = 500.0     # play "unlocked and continued story", clear banner

CURRY_MUSIC = os.path.join(EXP_DIR, "mondamusic-retro-arcade-game-music-512837.mp3")
CURRY_SIGN = "Curry Student Center: After Hours concert"
CURRY_IN_M = 675.0     # fade the arcade music IN + show the Curry sign
CURRY_OUT_M = 720.0    # fade it back OUT, clear the sign
CURRY_FADE_MS = 2000

# (with --retrigger) how far BELOW a beat's trigger the rider must drop before
# it re-arms -- hysteresis so OCR jitter near the line can't re-fire it.
REARM_MARGIN_M = 30.0

# Background ambience: keep 1-3 of the 4 loops alive, fading one in/out at random
# so the bed evolves instead of looping obviously. It stays LOW and always has
# >=1 loop up, so it's a quiet bed under Emma / Ruggles / Curry the whole ride.
BG_MIN, BG_MAX = 1, 3
BG_VOLUME = 0.45
BG_FADE_MS = 2500
BG_CHANGE_MIN, BG_CHANGE_MAX = 6.0, 14.0

# RIDING is "sticky": current_distance OCR is noisy at speed, so a valid frame
# only has to appear within this window to keep us in RIDING. Without this, brief
# invalid stretches dropped to IDLE and (previously) replayed the whole tour.
RIDING_STICKY_SECS = 8.0


def _esc_pressed():
    """True if ESC is down anywhere (global). The click-through overlay never
    holds focus, so a normal key binding can't catch a quit -- this polls the
    system key state instead, giving a kill switch that works mid-ride even when
    Rouvy or another window is focused."""
    try:
        return bool(ctypes.windll.user32.GetAsyncKeyState(0x1B) & 0x8000)
    except Exception:
        return False


def parse_region(s):
    left, top, width, height = (int(v) for v in s.split(","))
    return {"left": left, "top": top, "width": width, "height": height}


def to_meters(reading):
    if not isinstance(reading, tuple):
        return None
    num, unit = reading
    if isinstance(unit, str) and unit.strip().lower().startswith("km"):
        return num * 1000.0
    return float(num)


def _abs_grab(region, box):
    x1, y1, x2, y2 = box
    return {"left": region["left"] + x1, "top": region["top"] + y1,
            "width": x2 - x1, "height": y2 - y1}


def _read_box(sct, grab, thr, psm):
    shot = np.array(sct.grab(grab))[:, :, :3]
    h, w = shot.shape[:2]
    return hud_reader.read_region(shot, (0, 0, w, h), "unit_value", thr, psm)


def _ocr_contains(sct, grab, needle):
    img = np.array(sct.grab(grab))[:, :, :3]
    return needle in pytesseract.image_to_string(img, config="--psm 7").strip().lower()


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--region", default="1920,0,1920,1080")
    ap.add_argument("--config", default="configs/campus_bike_1.json")
    ap.add_argument("--delay", type=float, default=5.0)
    ap.add_argument("--duration", type=float, default=600.0)
    ap.add_argument("--trigger-m", type=float, default=87.0, help="Emma fires at this distance")
    ap.add_argument("--hold", type=float, default=5.0, help="seconds Emma stays on screen")
    ap.add_argument("--welcome-secs", type=float, default=6.0)
    ap.add_argument("--retrigger", action="store_true",
                    help="re-arm each beat when you loop back below it, so the "
                         "fades replay every approach (default: once per ride)")
    ap.add_argument("--audio", default=None, help="music bed (default: first data/*.mp3)")
    args = ap.parse_args()

    region = parse_region(args.region)
    cfg = hud_reader.load_config(args.config)
    cur = cfg["current_distance"]
    rem = cfg["remaining_distance"]
    cur_grab = _abs_grab(region, cur["box"])
    rem_grab = _abs_grab(region, rem["box"])
    preride_grab = _abs_grab(region, PRERIDE_BOX)
    pause_grab = _abs_grab(region, PAUSE_BOX)

    if args.delay > 0:
        print(f"overlay in {args.delay:.0f}s -- switch to the Rouvy monitor.")
        time.sleep(args.delay)

    ov = RideOverlay(region)
    sct = mss.mss()
    bed = AudioBed()
    print(f"[audio] {'ready' if bed.available else 'no device -- silent'}; clips in {EXP_DIR!r}")
    print("[hint] press ESC anytime (even with Rouvy focused) to close the overlay.")

    start = time.monotonic()
    last_dist_ocr = last_state_ocr = -999.0
    state = None
    last_valid_time = -999.0
    last_pos = None

    st = {}

    def rearm():
        bed.stop_all(fade_ms=400)
        st.update(emma_fired=False, emma_clear_at=None,
                  welcome_done=False, welcome_until=None,
                  alert_showing=False, alert_until=0.0, next_alert_at=0.0, gap=0.0,
                  ruggles_approach_fired=False, ruggles_unlock_fired=False,
                  ruggles_banner_active=False,
                  curry_started=False, curry_done=False, curry_active=False,
                  bg_on=False, bg_active=set(), bg_next_change_at=0.0)
    rearm()

    def bg_start():
        st.update(bg_on=True, bg_next_change_at=now)   # evolve immediately

    def bg_stop():
        for cid in list(st["bg_active"]):
            bed.stop(cid, fade_ms=BG_FADE_MS)
        st.update(bg_on=False, bg_active=set())

    def bg_tick():
        """Keep 1-3 loops alive, fading one in/out at random intervals."""
        if not (bed.available and st["bg_on"]) or now < st["bg_next_change_at"]:
            return
        active = st["bg_active"]
        idle = [c for c in BG_CLIPS if c not in active]
        can_add = bool(idle) and len(active) < BG_MAX
        can_remove = len(active) > BG_MIN        # never drop below 1 -> always on
        if can_add and (not can_remove or random.random() < 0.6):
            clip = random.choice(idle)
            bed.play(clip, clip, loop=True, fade_ms=BG_FADE_MS, volume=BG_VOLUME)
            active.add(clip)
        elif can_remove:
            clip = random.choice(list(active))
            bed.stop(clip, fade_ms=BG_FADE_MS)
            active.discard(clip)
        st["bg_next_change_at"] = now + random.uniform(BG_CHANGE_MIN, BG_CHANGE_MAX)

    try:
        while True:
            now = time.monotonic()
            if now - start >= args.duration:
                break
            if _esc_pressed():
                print("ESC pressed -- closing overlay.", flush=True)
                break

            # --- distance every 0.5s: read current + remaining, validate ---
            if now - last_dist_ocr >= 0.5:
                last_dist_ocr = now
                c = to_meters(_read_box(sct, cur_grab, cur.get("threshold"), cur.get("psm", 7)))
                r = to_meters(_read_box(sct, rem_grab, rem.get("threshold"), rem.get("psm", 7)))
                valid = c is not None and r is not None and abs(c + r - TOTAL_M) <= TOL_M
                if valid:
                    last_pos, last_valid_time = c, now
                print(f"t={now-start:5.1f}s cur={c} rem={r} valid={valid} pos={last_pos} state={state}",
                      flush=True)

                # Emma (validated distance, once per ride, RIDING only)
                if (state == "RIDING" and not st["emma_fired"] and valid
                        and last_pos >= args.trigger_m):
                    ov.clear_transient()
                    ov.show_speech_bubble(EMMA, 310, 80)
                    st.update(emma_fired=True, emma_clear_at=now + args.hold)
                    print(f">>> Emma fired at {last_pos} m", flush=True)

                # experience audio: the Ruggles beats (validated distance, once each)
                if valid and last_pos is not None:
                    if not st["ruggles_approach_fired"] and last_pos >= RUGGLES_APPROACH_M:
                        bed.play("ruggles", RUGGLES_APPROACH, fade_ms=300)
                        ov.clear_transient()
                        ov.show_banner("Landmark ahead: Ruggles (100m)")
                        st.update(ruggles_approach_fired=True, ruggles_banner_active=True)
                        print(">>> Ruggles approaching (400 m)", flush=True)
                    if not st["ruggles_unlock_fired"] and last_pos >= RUGGLES_UNLOCK_M:
                        bed.play("ruggles", RUGGLES_UNLOCKED, fade_ms=300)
                        ov.clear_transient()
                        st.update(ruggles_unlock_fired=True, ruggles_banner_active=False,
                                  alert_showing=False, next_alert_at=now)
                        print(">>> Ruggles unlocked (500 m)", flush=True)
                    if not st["curry_started"] and last_pos >= CURRY_IN_M:
                        bed.play("curry", CURRY_MUSIC, loop=True,
                                 fade_ms=CURRY_FADE_MS, volume=0.9)
                        ov.clear_transient()
                        ov.show_sign(CURRY_SIGN, 0.30, 0.55)
                        st.update(curry_started=True, curry_active=True)
                        print(">>> Curry / arcade music IN (675 m)", flush=True)
                    if (st["curry_started"] and not st["curry_done"]
                            and last_pos >= CURRY_OUT_M):
                        bed.stop("curry", fade_ms=CURRY_FADE_MS)
                        ov.clear_transient()
                        st.update(curry_done=True, curry_active=False,
                                  alert_showing=False, next_alert_at=now)
                        print(">>> Curry / arcade music OUT (720 m)", flush=True)

                    # RETRIGGER (opt-in): once the rider drops clearly BELOW a
                    # beat's trigger -- looped the course, or Rouvy restarted the
                    # route without a PRERIDE -- re-arm it so it fires again on
                    # the next approach. Same live-distance logic; just repeatable.
                    if args.retrigger:
                        if st["emma_fired"] and last_pos < args.trigger_m - REARM_MARGIN_M:
                            st["emma_fired"] = False
                        if (st["ruggles_approach_fired"]
                                and last_pos < RUGGLES_APPROACH_M - REARM_MARGIN_M):
                            st.update(ruggles_approach_fired=False, ruggles_banner_active=False)
                        if (st["ruggles_unlock_fired"]
                                and last_pos < RUGGLES_UNLOCK_M - REARM_MARGIN_M):
                            st["ruggles_unlock_fired"] = False
                        if st["curry_started"] and last_pos < CURRY_IN_M - REARM_MARGIN_M:
                            st.update(curry_started=False, curry_done=False)

            # keep the ambient bed evolving + reap finished one-shots
            if state in ("RIDING", "PAUSED"):
                bg_tick()
            bed.update()

            # --- state every 0.7s (context-aware: 1 OCR/tick) ---
            if now - last_state_ocr >= 0.7:
                last_state_ocr = now
                riding_signal = (now - last_valid_time) < RIDING_STICKY_SECS
                if state in (None, "PRERIDE", "IDLE"):
                    if _ocr_contains(sct, preride_grab, "resume ride"):
                        new = "PRERIDE"
                    else:
                        new = "RIDING" if riding_signal else "IDLE"
                else:  # RIDING or PAUSED
                    if _ocr_contains(sct, pause_grab, "continue ride"):
                        new = "PAUSED"
                    else:
                        new = "RIDING" if riding_signal else "IDLE"

                if new != state:
                    state = new
                    if state == "PRERIDE":
                        ov.clear_transient(); ov.clear_bubble()
                        ov.set_status("TOUR READY TO BEGIN"); rearm()
                    elif state == "PAUSED":
                        ov.clear_transient(); ov.set_status("PAUSED")
                    elif state == "IDLE":
                        # Blank the overlay on Rouvy's main screen, but do NOT
                        # rearm here: a new ride is signalled by PRERIDE, and
                        # rearming on IDLE made welcome/Emma/audio replay every
                        # time a noisy read briefly dropped RIDING -> IDLE.
                        ov.clear_transient(); ov.clear_bubble(); ov.clear_status()
                        bg_stop()
                    else:  # RIDING
                        ov.set_status("COMPANION TOUR ACTIVE")
                        st.update(alert_showing=False, next_alert_at=now)
                        if not st["bg_on"]:
                            bg_start()
                    print(f"state -> {state}", flush=True)

            # --- RIDING behaviours: welcome once, then the ambient "Photo spot"
            # alert. Emma AND the Ruggles banner are EXCLUSIVE: while either owns
            # the screen, the ambient alert is suppressed so nothing overwrites it.
            if state == "RIDING":
                exclusive = (st["emma_clear_at"] is not None or st["ruggles_banner_active"]
                             or st["curry_active"])
                if not st["welcome_done"]:
                    if st["welcome_until"] is None:
                        ov.clear_transient(); ov.show_banner(WELCOME)
                        st["welcome_until"] = now + args.welcome_secs
                    elif now >= st["welcome_until"]:
                        st.update(welcome_done=True, next_alert_at=now)
                        ov.clear_transient()
                elif not exclusive:
                    if st["alert_showing"]:
                        if now >= st["alert_until"]:
                            ov.clear_transient()
                            st.update(alert_showing=False, next_alert_at=now + st["gap"])
                    elif now >= st["next_alert_at"] and last_pos is not None:
                        ov.show_sign("Photo spot", 0.30, 0.55)
                        st.update(alert_showing=True, alert_until=now + 4.0,
                                  gap=random.uniform(10.0, 20.0))

            if st["emma_clear_at"] and now >= st["emma_clear_at"]:
                ov.clear_bubble()
                st.update(emma_clear_at=None, alert_showing=False, next_alert_at=now)

            ov.update()
            time.sleep(0.02)
    except KeyboardInterrupt:
        pass
    finally:
        bed.close()
        ov.close()
        print("overlay closed.")


if __name__ == "__main__":
    main()
