# Rouvy Companion — Campus Ride Experience

A companion layer for indoor cycling on **Rouvy**. It reads the rider's live
stats off the Rouvy screen by OCR (Rouvy has no API), then paints a synced
audio + visual experience on top: a narrated campus tour, and persistent
"artifacts" a rider records and leaves behind for the next rider to find.

Validated live on the campus rig (Aug 2026). **Windows-only** (screen capture +
click-through overlay + gamepad input).

---

## Setup

Requires **Python 3.12**, **Tesseract OCR 5.x** on `PATH`, and (for the record
demo) an **Xbox-style gamepad**.

```
pip install pytesseract mss opencv-python numpy pygame imageio-ffmpeg
python -m pytest          # expect: 73 passed, 3 xfailed (known OCR cells)
```

OCR boxes are calibrated **per monitor + window layout** — not portable. The rig
profile is `configs/campus_bike_1.json` (see `docs/campus-bike-1.md`). Re-verify
with a snapshot before trusting it; recalibrate with `find_hud_coords.py` if the
window/display moved. Rouvy must run **windowed/borderless** (exclusive
fullscreen returns frozen frames to the capture).

---

## The two live demos

Run with Rouvy on the external monitor and a ride loaded + rolling.

**1) Single-person audio tour** — companion overlay + layered audio (a quiet
background bed, Emma the guide at ~87 m, Ruggles at 400/500 m, a Curry/arcade
beat 675→720 m). Every beat is programmatic (fires on live distance). **ESC**
closes it even with Rouvy focused.

```
python single_person_audio_tour_demo.py --region 1920,0,1920,1080 --delay 5
#   add --retrigger to replay each beat every lap
```

**2) Async persistent artifacts** — pedal + gamepad to leave things behind:

```
python async_persistent_artifacts_demo.py --live --reset \
    --region 1920,0,1920,1080 --device "Microphone Array (2- Realtek(R) Audio)"
#   A = record a voice memory, 1/2/3 = drop a trinket, Q = quit
```

Hear them back on a later lap (same store):

```
python route_artifacts_poc/demo_audio_memories.py \
    --store output/audio_memories_store.json --live --region 1920,0,1920,1080
```

Before the rig: `python probe_input.py` (check the gamepad) and
`python mic_check.py` (confirm the mic actually captures — a silent file usually
means the wrong device or a Windows mic-privacy block).

---

## File map

**Core pipeline**
| file | what it does |
|---|---|
| `hud_reader.py` | OCR of one HUD region → value (pure; the heart of it) |
| `border.py` | crop/border helper used by `hud_reader` |
| `overlay.py` | transparent, click-through, always-on-top overlay (tkinter + Win32) |
| `audio_bed.py` | multi-channel audio: layer / fade / stop clips by name |
| `input_trigger.py` | gamepad + keyboard → abstract "leave a message" actions |
| `record_audio.py` | short mic clip via the bundled ffmpeg (dshow) |
| `live_source.py` | screen capture (`mss`) → frames |
| `stream_hud.py` | video/live → per-frame JSONL of readings |
| `live_readout.py` | live/file readout table |

**Live demos**
| file | what it does |
|---|---|
| `single_person_audio_tour_demo.py` | the narrated tour (overlay + audio) |
| `async_persistent_artifacts_demo.py` | record/leave artifacts while riding |
| `demo_experience.py` | offline "Curry" video artifact (needs a `data/training` video) |
| `demo_overlay.py` | scripted overlay preview (no rig needed) |

**Rig / calibration utilities**
| file | what it does |
|---|---|
| `find_hud_coords.py` | grid + place OCR boxes on a snapshot |
| `probe_input.py` | what does a controller look like to this PC? |
| `mic_check.py` | is an input actually capturing (not silent)? |
| `summarize_live_run.py` | quick frozen/plausibility check of a JSONL |
| `verify_stream.py` | JSONL vs the route-sum invariant + `expected.json` |
| `repair_stream.py` | rebuild a bad `remaining_distance` from the invariant |
| `repair_elevation.py` | smooth single-frame `max_elevation` misreads |

**Folders**
| path | what it holds |
|---|---|
| `route_artifacts_poc/` | persistent artifacts: drop → persist → discover (`route_artifacts.py` is the tested core; `demo_leave_message.py` is the async demo's engine; `demo_audio_memories.py` plays them back) |
| `debug-scripts/` | one-off OCR diagnostics (run from the repo root) |
| `configs/` | per-monitor OCR box configs (`campus_bike_1.json` = the rig) |
| `docs/` | calibration profile + feature designs |
| `test_crops/` | static crops for `test_hud_reader` |
| `data/prototype-demo/` | the experience audio (background / Ruggles / Curry clips) |
| `data/training/` | source videos — **git-ignored**, see its README |

---

See **`CLAUDE.md`** for the design principles and the hard-won OCR/overlay
gotchas before changing the pipeline.
