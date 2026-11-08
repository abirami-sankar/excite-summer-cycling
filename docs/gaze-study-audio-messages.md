# Gaze Study: Human Audio Messages

**Branch:** `human-audio-msg-gaze-study` · **Script:** `gaze_audio_messages_demo.py`
· **Status:** items 1, 2, 3, 6, 7 decided and built; **items 5 and 8 need design
input** before the study runs.

## What the rider experiences

While riding the campus loop (1344 m) in Rouvy, the rider **hears** short human
voice messages as they pass set spots on the route, and can **record** their own
message with the gamepad's A button. The tour overlay is stripped down so that
every visual is tied to a fixed route position, never a random time (see the
`stripped-overlay-gaze-study` branch).

## Decisions (built)

| # | Topic | Decision |
|---|---|---|
| 1 | Mic picking up playback | Pressing record **fades out** every playing clip. A clip reached *during* the recording is held, then plays once the recording has fully finished, if the rider is still within 100 m of its spot. Otherwise it's skipped and logged. |
| 2 | Hearing clips again | Each **lap** (distance wraps from ~1344 m back to ~0) re-reads `demo_voices/` and re-arms every clip. A new ride (Rouvy's "resume ride?" dialog) does the same. |
| 3 | Whose messages play | **Only the prepared samples in `demo_voices/`**, presented as other riders' messages. Participants' own recordings are saved for analysis but **never played back**, to them or anyone else. Because the team controls every clip, there's no crowding problem: spacing is set by the file names. |
| 6 | Pause / idle | Same screen-state detection as the audio tour. Clips start **only while riding**. Pausing or leaving the ride fades out what's playing. A clip reached but not yet played survives a pause. Recording is allowed only while riding. |
| 7 | Event log | One CSV per session in `output/gaze_logs/gaze_<rider>_<date>_<time>.csv`. The **`unix_time`** column (ms precision) is for syncing with the eye tracker's clock. |

### Event log columns

`unix_time, iso_time, t_s, event, state, lap, position_m, clip, author, detail`

| `event` | Meaning |
|---|---|
| `session_start` / `session_end` | script started / stopped |
| `state` | Rouvy screen changed: PRERIDE / RIDING / PAUSED / IDLE |
| `lap_start` | rider crossed the start line again |
| `clip_start` | a voice clip began (fades in over 0.7 s) |
| `clip_end` | the clip finished on its own |
| `clip_stop` | the clip was faded out; `detail` = `passed` / `recording` / `paused` / `lap` / `new ride` |
| `clip_hold` / `clip_skip` | clip reached during a recording; held, or missed because the rider rode past |
| `record_start` / `record_end` | rider recorded a message; `record_end` gives the file size (0 bytes = mic problem) |
| `record_refused` | A pressed but ignored (not riding / already recording / no position yet) |

## Needs design input

### Item 5: Should anything appear on screen when a clip plays?

**Currently:** nothing. Playback is audio-only. The only overlay items are the
status chip (left edge) and the red "● RECORDING" countdown.

| Option | For gaze | Trade-off |
|---|---|---|
| **A. Audio only** (current) | Cleanest: any gaze shift is a response to *sound*, not a visual cue | Riders may not know who's speaking or that a clip is a "message" |
| **B. Small fixed chip**, e.g. "🔊 message from Alex" in one fixed spot | Gives the eye tracker a known area of interest to measure dwell / glances | Adds a visual stimulus that competes with the road; may change behaviour vs A |
| **C. Sign placed in the scene**, near where the message was "left" | Tests whether people look toward a message's place | Rouvy's camera moves, so a fixed overlay can't track a point in the world. Only an approximation is possible |
| **D. Between-subjects condition**, A vs B | Lets the study *measure* the effect of the visual | Needs more participants; the script would need a `--visual` flag |

**Questions for the team**
1. Is the research question about attention to the **voice** (→ A) or about how a
   **visual** cue changes attention (→ B or D)?
2. If there's a visual: what text (name? "message"? icon only?), where on screen,
   and for how long (the whole clip, or a few seconds)?

### Item 8: Free recording or prompted recording?

**Currently:** free. The rider can press A anywhere, any time while riding.

| Option | For the study | Trade-off |
|---|---|---|
| **A. Free** (current) | Natural behaviour; you learn *where* people choose to record | Recording spots differ per participant, so gaze data is harder to compare |
| **B. Prompted at fixed spots**: a short spoken prompt ("Leave a message for the next rider?") at chosen metre marks; A to accept | Same spots for every participant → directly comparable | The prompt itself is an audio stimulus, so it must be logged and designed (voice, wording, length) |
| **C. Prompted, recording only allowed at the prompts** | Most controlled | Least natural; riders can't react to what they see |
| **D. Prompted + free** | Comparable spots plus natural extras | Two kinds of recordings to analyse separately |

**Questions for the team**
1. Is *where riders choose to record* part of the research question (→ A or D),
   or only *what happens to gaze while recording* (→ B or C)?
2. If prompted: how many prompts per lap, at which metre marks, and should a
   prompt avoid overlapping a voice clip?
3. Is 5 s the right recording length? It's a `--seconds` setting. Should there be
   a "press again to stop early" option?

## How to run

On the rig (Rouvy windowed/borderless on the external monitor):

```
python gaze_audio_messages_demo.py --live --region 1920,0,1920,1080 \
    --device "Microphone Array (2- Realtek(R) Audio)" --rider P01
```

At a desk, with no bike (synthetic ride, keyboard SPACE to record):

```
python gaze_audio_messages_demo.py --simulate
```

- **Clips:** put them in `demo_voices/`. The file name sets the route position
  (`300m_alex_good-luck.mp3`); see `demo_voices/README.md`.
- **Mic:** run `mic_check.py` before each session. A 0-byte `record_end` in the
  log means the wrong device or a Windows mic-privacy block.
- **Quitting:** quit with **ESC** (works with Rouvy focused) so in-progress
  recordings finish writing.

## Known limits

- **Speakers:** with speakers, not headphones, mic bleed is handled by fading
  out playback during recording. A clip that *starts* right after a recording
  can still be picked up if ffmpeg is slow to release the mic. Headphones remove
  this entirely.
- **Recalibration:** the screen-state boxes are shared with the audio tour.
  Recalibrate both together if the Rouvy window moves.
- **Playback start:** a clip starts ~30 m before its spot and fades out ~100 m
  after it. Two clips within that window overlap.
