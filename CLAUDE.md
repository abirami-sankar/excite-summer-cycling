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
  LEAVE = `demo_leave_message.py` (pad A / SPACE = record 5 s, buttons 1/2/3 =
  trinket, global ESC = quit); HEAR = `demo_audio_memories.py`. Both share
  `output/audio_memories_store.json`. Old brookline-north POCs are in
  `route_artifacts_poc/archive/` (not used by the rig).

## Eye-tracking (gaze) study branches
Study builds live on branches; **`main` stays untouched** (still `9f8d4d4
Initial commit`) until the study is done — never commit/merge to it without an
explicit ask. Both branches are pushed to `origin` with upstream tracking.

```
main (9f8d4d4) ── stripped-overlay-gaze-study ── human-audio-msg-gaze-study
                  (tour visuals stripped)        (branched FROM stripped; adds
                                                  voice messages + study script)
```
- **Workflow**: tour-visual changes → commit on `stripped-overlay-gaze-study`,
  then `git checkout human-audio-msg-gaze-study && git merge
  stripped-overlay-gaze-study` so the voice branch inherits them. Voice/study
  changes → `human-audio-msg-gaze-study` only. This CLAUDE.md is kept identical
  on both branches.
- **Status (Nov 2026)**: all code is unit-tested + desk-simulated ONLY — nothing
  from either branch has been run on the rig with Rouvy, the Xbox pad, or the
  real mic yet. `demo_voices/` holds only its README (no clips yet).

- **`stripped-overlay-gaze-study`** — audio tour with the random "Photo spot"
  pop-ups AND the "Landmark ahead: Ruggles" banner removed (Ruggles AUDIO still
  plays at 400/500 m). Every remaining visual is tied to a fixed route position
  (welcome, Emma ~87 m, Curry sign 675–720 m, status chip) — nothing appears at
  a random time, so gaze data lines up with route position.
- **`human-audio-msg-gaze-study`** (branched from the above) — human voice
  messages:
  - `demo_leave_message.py` now has the tour's PRERIDE/RIDING/PAUSED/IDLE
    state machine (same `PRERIDE_BOX`/`PAUSE_BOX` — recalibrate BOTH scripts
    together); presses accepted ONLY in RIDING; position cleared on
    PRERIDE/IDLE (no pinning at a stale spot); red click-through
    "● RECORDING Ns" countdown; overlapping record presses refused.
  - `demo_audio_memories.py` plays human clips from **`demo_voices/`** (project
    root), placed by FILE NAME (`300m_alice_caption.mp3`, `1.05km_…`, bare
    number = metres, no prefix = spaced evenly) — read fresh each run, NOT
    copied into the store — merged with rider recordings from the store. The old
    generated placeholder tones are gone. (This standalone HEAR script still
    has no pause/idle handling or per-lap replay; the combined script does.)
  - **`gaze_audio_messages_demo.py`** (root) — THE study script: record + hear
    in one loop. Plays ONLY `demo_voices/` clips (decision: participants'
    own recordings are saved, never played back). Ducks playback on record and
    holds clips reached mid-recording; re-arms clips each lap (valid distance
    wraps to ~0) and on PRERIDE; RIDING-only playback/recording; CSV event log
    in `output/gaze_logs/` (`unix_time` = eye-tracker sync column). Pure logic
    (`ClipScheduler`, `is_new_lap`) tested in `test_gaze_audio_messages.py`.
    Open design input (visual on playback; free vs prompted recording):
    `docs/gaze-study-audio-messages.md`. Trinket buttons are ignored here
    (record only). Recordings index to `output/gaze_recordings_store.json`
    (separate from the older demos' `audio_memories_store.json`).
    Run: `python gaze_audio_messages_demo.py --live --region 1920,0,1920,1080
    --device "<mic>" --rider P01` (desk: `--simulate`, SPACE = record).
  - **`demo_voices/` is tracked on purpose** (shared test data anyone can pull):
    `.gitignore` ends with `!demo_voices/` + `!demo_voices/**` — keep those
    LAST. Keep clips small (GitHub rejects files >100 MB).

### Gaze study — next steps (in order)
1. Add the human voice clips to `demo_voices/` (name = position, see its
   README), commit + push on `human-audio-msg-gaze-study`.
2. Rig validation of `gaze_audio_messages_demo.py`: `mic_check.py` first;
   confirm the Xbox pad's A = button 0 (`probe_input.py`); check the
   PRERIDE/PAUSE boxes still match the Rouvy window; ride ≥2 laps and confirm
   per-lap replay + a sane CSV log (0-byte `record_end` = mic problem).
3. Team decides items 5 + 8 in `docs/gaze-study-audio-messages.md`, then build
   them into the study script.
4. Known limit: on SPEAKERS a clip starting right after a recording can bleed
   into the mic if ffmpeg is slow to release it — recommend headphones.

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
- Git from PowerShell 5.1: a commit message containing double quotes in a
  `-m @'…'@` here-string gets split into pathspecs → write the message to a
  file and use `git commit -F <file>`.

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
- **Gaze study**: see "Gaze study — next steps" above.

See `docs/` for the calibration profile and feature designs, and `README.md` for
setup + the file map.
