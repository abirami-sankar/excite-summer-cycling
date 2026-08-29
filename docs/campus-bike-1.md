# Calibration profile: "campus bike 1"

Saved live-capture calibration for the **campus monitor rig** so we can reload
it instead of recalibrating each session. First profile calibrated against
**actual Rouvy** (not a recorded-clip proxy).

- **Calibrated:** 2026-08-04, live on the campus rig.
- **Loadable artifact:** [`configs/campus_bike_1.json`](../configs/campus_bike_1.json) — the HUD box config. This is the thing you "load"; everything below is how to use it.
- **Route at calibration:** "Northeastern Boston Campus (TEST)", ~1.34 km total, with pace partner **Anna** enabled (2-rider panel).

## Hardware / display context (must match to reuse without recalibrating)

| Item | Value |
|------|-------|
| Capture monitor | External **Sony** display (`unique_id` contains `SNYF303`) |
| Monitor geometry | `left=1920, top=0, width=1920, height=1080` (it sat to the RIGHT of the laptop's primary 1920×1080 `IVO0621`) |
| `--region` value | `1920,0,1920,1080` |
| Rouvy window state | Riding view, **windowed/borderless (NOT exclusive fullscreen)**, on the external monitor |

> **Bug #8 warning:** these boxes are pixel-locked to this monitor + window
> layout. If the display arrangement changes (monitor unplugged/re-ordered, so
> the external monitor is no longer at `left=1920`) or the Rouvy window is
> moved/resized, re-enumerate and recalibrate. Confirm the region first with
> `python live_source.py` — if the Sony monitor isn't at `left=1920,top=0`,
> update `--region` to wherever it now is.

## Run the live readout

From the `project-cycling-wrapper` folder, with Rouvy **riding** on the external monitor:

```
python live_readout.py --live --region 1920,0,1920,1080 \
  --config configs/campus_bike_1.json --fps 2 --duration 60 \
  --fields power,current_distance,remaining_distance,current_elevation,partner_gap
```

- `--duration` = seconds to run; `--fps` = samples/sec; `--fields` = columns (add `gradient,max_elevation` to show them).
- `--debug-save output/frame.png` dumps the first grabbed frame if you want to confirm box alignment.

## Quick re-verify (before trusting a run)

```
python -c "import cv2,hud_reader; from live_source import snapshot; \
snapshot({'left':1920,'top':0,'width':1920,'height':1080},'output/check.png'); \
print(hud_reader.extract_hud(cv2.imread('output/check.png'), hud_reader.load_config('configs/campus_bike_1.json')))"
```
Eyeball the printed reads against the on-screen HUD. If they line up, the profile still holds.

## Fields on this HUD layout

| Field | Status | Notes |
|-------|--------|-------|
| `power` | ✅ reliable | big italic, `psm:8`; honest `None` on motion blur |
| `current_distance` | ✅ reliable | handles both `865 m` (3-digit) and `23 m`; right-anchored box widened to `x1=705` |
| `remaining_distance` | ✅ reliable | handles both `478 m` and `1.32 km`; box widened to `x1=845` |
| `current_elevation` | ✅ reliable | reads `0 m`/`1 m` |
| `partner_gap` | ✅ good (phase-1 signal) | Anna's gap; **occasionally drops the leading `-`** on a blurred frame (thin minus stroke) — gap is monotonic so the sign is recoverable |
| `max_elevation` | ⚠️ calibrated, watch it | known graphic-bleed risk when the elevation profile scrolls behind it |
| `gradient` | ⚠️ nice-to-have | `psm:11`; reads `-0.6` when clean, honest `None` on some frames |
| speed / cadence | ❌ not available | this Rouvy layout doesn't display them — nothing to OCR. Enable those tiles in Rouvy's *Customize interface* and recalibrate if needed. |

## Distance format gotcha (baked into the boxes already)

Rouvy shows distance in **meters below ~1 km** (`865 m`, right-anchored, grows
leftward as digits are added) and **km above** (`1.32 km`). Both distance boxes
were widened so they read *either* format — verified on a 2-digit-meter frame,
a 3-digit-meter frame, and a km frame. If a value ever exceeds these (e.g. a
4-digit meter reading on a longer route), widen `x1` further and re-verify.

## Provenance / evidence

Calibrated by: snapshot the live external monitor → grid overlay
(`find_hud_coords.py --image --grid`) → place boxes → OCR-verify against the
visible HUD. Two real fixes came out of the real HUD (not the recorded proxy):
this font renders `1` as `L` (added `L`→`1` to `hud_reader._CONFUSABLE_DIGIT_MAP`),
and gradient needs `psm:11`. Live readout confirmed end-to-end during active
pedaling: `remaining_distance`, `partner_gap`, `power`, `current_elevation` all
tracked live and plausibly.
