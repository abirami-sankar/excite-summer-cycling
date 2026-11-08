# Feature Design: Persistent Route Artifacts + Proximity Voice Chat

> **Status:** Capability A (artifacts) has a working **proof of concept**
> (see §3.4); Capability B (proximity voice chat) and richer artifact
> types/backend/moderation are still design only. Several product decisions
> remain open and are flagged below. Depends on the route-position data
> produced by `feature-rider-panel-parsing.md` and by the existing
> `current_distance` OCR field (see `../CLAUDE.md`).

## 1. Overview

A shared social layer on top of a Rouvy ride. Up to **3 riders**, each in a
different physical location, all riding the **same Rouvy route map**. Two
capabilities:

- **A. Persistent route artifacts** — riders leave artifacts (text / audio /
  photo — *type not yet decided*) anchored to positions along the route.
  Artifacts **persist across ride sessions**: a later group of 3 riders finds
  earlier riders' artifacts along the route and can add their own. A **max
  threshold** bounds storage, with **periodic cleanup** to keep memory clean.
- **B. Proximity voice chat** — when two riders are within **~20 ft** of each
  other *along the route*, they can connect over voice chat.

Both capabilities are anchored to **route position**, which is derived from
the OCR pipeline — this feature does not read new pixels; it consumes the
distance/gap data the OCR layer already extracts.

## 2. Rider & world model

- **Riders:** up to 3 concurrent, geographically distributed, sharing one
  virtual route. (Contrast with phase 1 of the paired feature, which is 2
  riders; this feature's cap is 3.)
- **Route:** identified by a stable `route_id` (e.g. "Brookline North"). All
  positions and artifacts are namespaced under `route_id` so different routes
  don't collide.
- **Position:** each rider's location on the route is a **distance along the
  route** (km/m), sourced from:
  - `current_distance` (own position — already OCR'd today), and/or
  - the inter-rider **gap** from `roster_reader` (relative position).

  > **Key dependency:** "20 ft proximity" and "artifact at this spot" are both
  > defined in **route-distance space**, NOT physical GPS. The riders are in
  > different cities; what they share is the virtual route. So proximity =
  > their route-distance positions are within the threshold.

## 3. Capability A — Persistent route artifacts

### 3.1 Data model (sketch)
```
Artifact {
  id:          uuid
  route_id:    str            # namespacing
  position_m:  float          # anchor point along the route
  type:        "text" | "audio" | "photo"   # TBD — see open questions
  payload:     str | blob-ref # inline text, or a reference to stored media
  author:      rider_id
  created_at:  timestamp
}
```

### 3.2 Lifecycle
- **Create (drop):** a rider drops an artifact at their **current route
  position** (`position_m = current_distance`). Stored server-side, keyed by
  `(route_id, position_m)`.
- **Discover:** as a rider advances, when their `current_distance` crosses an
  artifact's `position_m` within a **trigger radius**, the artifact is
  surfaced (shown/played). This is the same "crossed a boundary" logic as the
  km-milestone banner in `demo_v1.py`, generalized to arbitrary anchor points.
- **Persist:** artifacts are NOT tied to a session; they survive session end
  and are visible to future rider groups on the same `route_id`.
- **Cleanup:** a **max artifact count** (per route, and/or global) bounds
  storage. When exceeded, a **periodic purge** removes artifacts by policy
  (oldest-first / FIFO is the simplest; alternatives: least-viewed, expiry by
  age). Purge cadence + policy are open questions.

### 3.3 Discovery matching
Discovery reuses the milestone-crossing pattern: maintain the rider's
monotonically increasing route distance, and fire when
`prev_distance < artifact.position_m <= current_distance` (within tolerance),
so an artifact fires once as it's passed, not repeatedly.

### 3.4 Proof of concept (BUILT)
The Capability-A core loop — **drop → persist → discover** — is implemented
and tested in `../route_artifacts_poc/`, text-only and file-backed per §7
phasing:

- **`route_artifacts.py`** — `ArtifactStore` (JSON-file persistence,
  route-namespaced, FIFO `prune()` for the max-threshold) + `ArtifactDiscoverer`
  (fire-once-on-crossing via a high-water mark, so a backwards OCR flicker
  never re-fires or skips). Position comes in as plain km numbers, so it's
  pure/unit-testable — same boundary as `hud_reader`.
- **`archive/demo_artifacts.py`** *(archived; not used by the live rig)* — terminal walkthrough driven by REAL OCR output:
  reads `current_distance` from a `stream_hud` JSONL (`run.jsonl`) as the
  rider's position, and simulates 3 sessions (Alice → Bob → Carol) sharing one
  store file to demonstrate cross-session persistence.
- **`archive/demo_artifacts_video.py`** *(archived)* — renders a showable ~20s clip
  (`output/demo_artifacts.mp4`): plays the real footage, OCRs the position
  live, and pops a discovery card as the rider reaches each artifact a
  previous rider left. Sped up (default 3×) so all discoveries fit in ~20s.
- **`test_route_artifacts.py`** — 11 tests: fire-once, position-order,
  backward-flicker tolerance, behind-start exclusion, trigger radius, file
  persistence across reopen, id uniqueness, route namespacing, FIFO prune.

What the POC does NOT cover yet (still design): media artifact types
(audio/photo), a shared multi-rider backend, moderation, cleanup cadence/
scheduling, and all of Capability B. Discovery here uses a rider's own
`current_distance`; a real deployment anchors drops the same way but stores
them server-side so OTHER riders (and later sessions) see them.

## 4. Capability B — Proximity voice chat

- **Trigger:** two riders whose route-distance positions are within
  **~20 ft (~6 m)** of each other become eligible to connect over voice.
- **Position source:** the OCR-derived route positions / gap (Capability's
  shared dependency). With ≤3 riders, this is pairwise: check each of the
  ≤3 pairs.
- **Connect:** open a voice channel between the two riders (transport, e.g.
  WebRTC, is out of OCR scope — this feature only supplies the *trigger*).
- **Disconnect + hysteresis:** to avoid flapping when riders hover near the
  threshold, connect at ≤6 m and disconnect only after they exceed a larger
  distance (e.g. >10 m) — a debounce/hysteresis band, exact values TBD.
- **Consent:** voice connections should be opt-in / require both riders'
  agreement (privacy — consistent with the project's stance in CLAUDE.md's
  "Rejected approaches" on not logging others' data without consent).

## 5. Dependencies

- **`current_distance` OCR** (exists) — own route position + artifact anchor.
- **`roster_reader.py` gap** (planned; see companion doc) — inter-rider
  relative position for proximity, when reading it off the leaderboard is
  more reliable than differencing two riders' `current_distance`.
- **A backend service** — for artifact persistence, the roster/position
  exchange between distributed riders, and voice signaling. This is new
  infrastructure beyond the current OCR-only repo.

## 6. Open questions / decisions

> For the eye-tracking study's audio-message build (on-screen visual during
> playback; free vs prompted recording), see
> [gaze-study-audio-messages.md](gaze-study-audio-messages.md).

**Artifacts**
1. **Artifact type** — text, audio, and/or photo? (Affects storage, moderation,
   and the discover UX.)
2. **Max threshold** — per-route cap? global cap? what number?
3. **Cleanup** — cadence (nightly? on-overflow?) and policy (FIFO / age /
   least-viewed)?
4. **Moderation** — persistent user-generated content visible to strangers
   needs a plan for abuse/reporting.
5. **Anchor granularity/tolerance** — how close must you be to "find" an
   artifact (trigger radius)?

**Proximity**
6. **Exact proximity threshold** — is "20 ft" firm, and in route-distance
   meters (~6 m)? Hysteresis band values?
7. **Position source of truth** — leaderboard gap vs. differenced
   `current_distance`, and how to reconcile OCR noise (a bad frame shouldn't
   spuriously trigger/drop a call — needs smoothing/debounce, like the
   planned OCR repairs).

**General**
8. **`route_id` identification** — how is the current route recognized
   (from the HUD? configured per session?) so artifacts land on the right map.
9. **Rider identity** — how riders are identified across sessions (name from
   the leaderboard vs. an app account).

## 7. Phasing suggestion

1. **Position plumbing first** — reliable per-rider route position from OCR
   (needs `roster_reader` + smoothing). Everything else depends on it.
2. **Artifacts (text-only) MVP** — simplest type; validates drop → persist →
   discover end to end with a minimal backend.
3. **Proximity trigger** — pairwise threshold + hysteresis on the position
   stream (voice transport can be stubbed/logged first).
4. **Richer artifact types + cleanup policy + moderation.**
