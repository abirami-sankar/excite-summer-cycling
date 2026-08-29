# Rouvy Companion — project guide (compact)

## What this is
Reads live ride stats (distance, power, elevation, pace-partner gap) off Rouvy's
on-screen HUD by **OCR** — Rouvy has no API and app/network scraping was ruled
out (ToS, fragile). On top of that live position it paints a companion
**experience**: a narrated campus audio tour, and persistent artifacts riders
leave for each other. Windows-only. Validated live on the campus rig, Aug 2026.

## Core principle
`hud_reader.extract_hud(frame, config) -> {name: value}` knows nothing about
video, screens, or timing — it only answers "what value is in this box?". So OCR
is testable on static images and identical for file vs live frames; all
video/streaming/timing lives outside it. `overlay.py`, `audio_bed.py`,
`input_trigger.py`, `record_audio.py` follow the same rule: each does ONE thing
and degrades gracefully (no audio device / no gamepad → safe no-op).

## Key concepts
- **Region config** (`configs/*.json`): each field has a box `[x1,y1,x2,y2]`, a
  `type` (int/float/str/unit_value), and optional `threshold`/`psm` overrides.
- **Route-sum invariant**: `current_distance + remaining_distance == route_total`
  every frame (campus = **1344 m**). Used to VALIDATE a live read (reject
  misreads) and to repair a bad `remaining_distance`. Re-measure per route.
- **Live capture**: `mss` grabs the Rouvy monitor region; Rouvy must be
  windowed/borderless (exclusive fullscreen → frozen frames). Boxes are
  per-monitor/-layout — recalibrate if the window moved.
- **Overlay**: tkinter borderless + `-topmost` + colorkey + Win32
  `WS_EX_TRANSPARENT` so ALL input passes through to Rouvy. Global **ESC** closes
  the tour (the click-through overlay never holds focus for a normal key bind).
- **audio_bed**: named clips on separate `pygame` channels → layer / fade / stop
  each independently (the single `mixer.music` bed could only do one stream).
- **input_trigger**: gamepad AND keyboard → abstract actions. The bike's own
  ABXY buttons are NOT visible to the PC (they talk to Rouvy over BLE) → use an
  Xbox pad. `SDL_JOYSTICK_ALLOW_BACKGROUND_EVENTS` lets it register while Rouvy
  is the focused app.

## The experience
- **single_person_audio_tour_demo.py**: an OCR state machine
  (PRERIDE/RIDING/PAUSED/IDLE, detected by OCR of on-screen text) fires beats by
  live distance — all PROGRAMMATIC (position crossing a threshold, not a clock
  or manual key). `--retrigger` re-arms each beat so it replays every lap.
- **async_persistent_artifacts_demo.py** + `route_artifacts_poc/`: record a
  voice memory / drop a trinket pinned to a position; it persists to disk; a
  later lap hears it on pass-by (fades in on approach, out once past).

## Gotchas (hard-won, evidence-based — a debug script confirmed each)
- Grayscale via `np.max(B,G,R)`, not `cvtColor` (preserves color-tinted text).
- Confusable letters→digits map for unit_value (`O/0 B/8 S/5 … L/1`); safe only
  because units (W/km/m/%) contain none of them.
- Italic power: `psm 8` + take the first digit run (the bolt icon OCRs as a
  stray `-`). Gradient: `psm 11`. Distances are right-anchored — the box must
  fit the widest case (3-digit metres AND the km form).
- `current_distance` is noisy at speed → VALIDATE with the route-sum invariant;
  RIDING is "sticky" and the per-ride re-arm (welcome/Emma/audio) happens ONLY
  on PRERIDE — never on a transient IDLE, or the whole tour replays on a bad read.
- Recording: WAIT for the background ffmpeg to finish before exit or the file is
  never written; run `mic_check.py` first (a silent file = wrong device or a
  Windows desktop-app mic-privacy block).

## Rejected (don't re-suggest without new info)
Scraping Rouvy's app/network (ToS, fragile); reading other riders' ANT+/BLE
(consent) — OCR of the visible HUD is the chosen path; template/char matching
instead of OCR.

## Next / open
- **iPad target**: an ARCHITECTURE rethink, not a port — iOS can't screen-capture
  or draw an overlay over another app. Decide the platform model (companion
  machine vs ReplayKit/broadcast vs on-device) BEFORE building.
- Wire route-artifacts discovery + a **ghost-rider** (a MOVING anchor on the same
  audio engine) to a live stream.
- **2 synced riders** (Option C: `gap = A_distance − B_distance`).

See `docs/` for the calibration profile and feature designs, and `README.md` for
setup + the file map.
