# Feature Design: Dwell-Tour POC (the summer probe)

> **Status: DESIGN for the summer POC probe. Scope chosen = "Option 1"**
> (companion prompts the rider to stop at a spot; if they dwell, audio
> unlocks). This is the **codesign probe** the professor required before
> the participatory-design workshop can run. Companion to
> `setup-proof-milestone.md` and `feature-route-artifacts-and-proximity.md`
> (this reuses that feature's route-anchor idea).

## 1. Purpose

The smallest showable thing that demonstrates the experience: a rider
rides a campus route; a companion voice points out spots ("there's
something here — stop if you want to hear it"); if the rider actually
**stops and lingers** at the spot, its **audio unlocks and plays**; if
they ride past, it stays locked. That's the whole loop.

It exists to (a) be a concrete probe that unblocks the stalled codesign
workshop, and (b) prove the experience mechanic end to end on real
footage — not to be the finished tour.

## 2. Why this is the low-risk option (and what it does NOT need)

Everything this POC needs is a signal we have **already proven** (see
`setup-proof-milestone.md` Layer 1):

- **Where the rider is** → `current_distance` (rock solid).
- **Whether they stopped** → `speed ≈ 0` (rock solid).

Crucially, **this POC does NOT need Layer 3 (the other-rider gap).** The
"companion" is our own narration layer, not a networked second rider — so
there is no relay, no clock-sync, no leaderboard/pace-partner read on the
critical path. It also does not need the button-press/input path (the
professor proved that feasibility separately; it is not used here). That
leaves a single-rider, read-only, recorded-data build — the smallest
surface that still shows the real experience.

## 3. Experience loop (rider POV) -- REVISED after the first live test

Two Rouvy constraints found on the rig reshaped the loop (see §3a):

```
   approach a marker
        │  audio FADES IN as you get closer (the lure -- felt, not spoken)
        ▼
   ┌─────────────── decision ───────────────┐
   │                                          │
 ride on                                 stop & dwell
   │                                          │  (Rouvy PAUSES -> pause screen)
   ▼                                          ▼
 audio FADES OUT                       pause screen becomes the CANVAS:
 (graceful miss)                       overlay an artifact IMAGE + audio at full
   │                                          │
   ▼                                          ▼
 keep riding                           resume pedaling -> image clears, route returns
```

The mechanic is now **audio-proximity lure → dwell-reveal on the pause screen**,
not "arrive → spoken prompt → stop." Getting closer raises the audio; stopping
turns Rouvy's (otherwise unavoidable) pause screen into the reveal surface;
riding past just fades it. Nothing is punished.

### 3a. Two Rouvy constraints that SHAPE this loop (found on the rig)

1. **Stopping = the pause screen.** The rider only sees the moving route WHILE
   pedaling; the instant they stop, Rouvy shows its pause screen. So the reward
   for dwelling can't live on the route view -- instead we make the **pause
   screen the intentional canvas**: our click-through overlay paints the
   artifact image on it while the audio plays. The constraint becomes the
   payoff. (Dwell is therefore detected by **pause-screen detection**, more
   robust than reading a zeroed speed.)
2. **The route is LINEAR.** You can't turn at intersections -- Rouvy follows the
   fixed route regardless. So markers/signs are **evocative, not navigational**
   ("Curry this way → After Hours concert" points at a place you *pass*, it does
   not offer a turn), and the route must be **heavily curated/planned** up front:
   every beat is placed against a known, fixed path. This is a curation cost, not
   a code problem.

## 4. Architecture — one new pure-logic module

Keep the project's core boundary: **pure logic (the tour state machine)
stays free of video/audio/timing I/O**, so it's testable on a recorded
`(distance, speed)` series with no video or live capture — exactly how
`route_artifacts_poc` is tested today.

- **Input:** the `(current_distance, speed)` time series `stream_hud`
  already emits as JSONL (identical shape across file/live modes, so this
  is source-agnostic by construction).
- **Reuses:** the route-anchor concept from `route_artifacts_poc`
  (position-anchored items in route-distance space) and its
  fire-once-per-anchor discipline.
- **Output:** a stream of events — `PROMPT(spot)`, `UNLOCK(spot)`,
  `PASS(spot)` — that an I/O layer (audio player, or a demo video overlay
  like `demo_v1.py` / `demo_artifacts_video.py`) renders. The state
  machine itself plays nothing.

### Per-marker state machine (revised for the pause-aware loop)
```
LOCKED
  → current_distance within audio_radius of marker       → APPROACHING [audio fades in ∝ closeness]
APPROACHING
  → PAUSE SCREEN detected near the marker (rider dwelled) → DWELLING    [artifact IMAGE on pause
                                                                         screen + audio at full]
  → current_distance passes the marker, still moving      → PASSED      [audio fades out]
DWELLING
  → pause screen clears (rider resumed pedaling)          → DONE        [clear image; route returns]
```
Dwell is detected by **pause-screen detection** (a distinct visual state, e.g.
the "PAUSED"/"CONTINUE RIDE" chrome), which is more robust than reading a
zeroed `speed` and fires exactly when the reveal canvas is up -- see §3a(1).

### Config (a `tour_config.json`, sibling to `hud_config.json`)
A list of spots, each:
```json
{
  "spot_id": "library-quad",
  "route_km": 0.42,
  "prompt_text": "There's something here — stop to hear it.",
  "audio_file": "audio/library-quad.mp3",
  "prompt_radius_km": 0.03,
  "stop_radius_km": 0.015,
  "dwell_seconds": 3.0
}
```
Radii/dwell are tunables to be set against real footage, not guessed
(same evidence-based discipline as the OCR boxes).

## 5. Testability

Drive the state machine with a hand-written or recorded `(distance,
speed)` series and assert the event sequence — e.g. "rider slows to 0
inside the stop radius for ≥ dwell_seconds → exactly one UNLOCK for that
spot"; "rider passes at speed → PASS, no UNLOCK". No video, no audio, no
campus rig needed. Mirrors `test_route_artifacts.py`.

## 6. Build path (what needs what)

- **Now, NO campus access:** build + unit-test the tour state machine
  against recorded JSONL (`run.jsonl` or a synthetic series). This is the
  heart of the POC and is fully unblocked today.
- **Desk, needs the campus video:** re-measure the route-total-distance
  constant on `data/training/RouvyCampusTest.mp4` (the 14.06 km value is
  Brookline-specific), validate the `hud_config.json` boxes line up on it
  via `find_hud_coords.py --image`, and produce a campus `stream_hud`
  JSONL to drive a showable overlay clip.
- **Campus-blocked:** the live end-to-end run on the prof/PhD
  monitor-connected bike (or the lab1 bike once wired) — the Layer-2
  proof, unchanged.

## 7. Deliberately deferred (codesign will decide)

- **Audio content + which campus route** — placeholder audio + the
  captured campus route for the probe; real content is the codesign output.
- **The "Option 2" scavenger/artifact-collection framing** — same engine,
  different skin; kept on the shelf, revisit if codesign prefers it.
- **The paired-ride other-rider gap (Layer 3), networking, voice chat,
  onboarding UX** — out of this POC entirely.

## 8. Experience-design depth (check-in feedback → next)

The latest check-in went well, but the professors wanted **more happening on
the experience-design side** — the sensing/OCR story is solid (the
screen-capture demo landed), so the next push is the *felt experience*, not
more plumbing. Concrete threads to develop (design work, largely no code):

- **The companion's persona & voice.** Who is talking to the rider — a tour
  guide, a peer/upperclassman, the place itself? What's their tone (warm,
  playful, factual)? This choice drives everything the rider hears.
- **The moment-to-moment loop, written as a script.** Storyboard one spot end
  to end: the approach cue, the invitation to stop, the pause, the payoff
  audio, and the "ride on" if they don't stop. What words, what timing, what
  sound design?
- **Why lingering is rewarding.** The mechanic is "stop → unlock," but the
  *reason to stop* has to be emotionally worth it (a story, a secret, a
  connection). Define what the payoff feels like, not just that it fires.
- **Handling the skip / missed spot gracefully.** What does the rider
  experience if they ride past — silence, a soft "we'll catch it next time,"
  a chance to come back? This is a felt moment too.
- **The arc across spots.** Three or four spots should feel like *a tour*
  with a shape (opening, build, payoff), not disconnected pings.

These are exactly what the codesign workshop is meant to shape *with*
students — so this section is the brief to bring into that session, and the
place to expand as the experience gets designed. The dwell-tour engine (§4)
is the substrate that makes any of these playable.
