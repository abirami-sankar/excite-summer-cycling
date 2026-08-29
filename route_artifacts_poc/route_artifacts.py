"""
route_artifacts.py

Proof of concept for the PERSISTENT ROUTE ARTIFACTS feature (see
docs/feature-route-artifacts-and-proximity.md). Riders leave artifacts
(text-only in this POC) pinned to a POSITION ALONG THE ROUTE (distance in
km) -- NOT to a session or a wall clock. That's the whole point: an artifact
outlives the ride that dropped it, so the next rider group finds it and adds
their own.

The core loop this proves, end to end:

    drop  ->  persist (survives process exit)  ->  discover (fire once when crossed)

Design choices, and why:
  * Position comes in as PLAIN NUMBERS (km), not pixels. The route position
    is already produced reliably by the OCR pipeline (current_distance), so
    this module stays ignorant of video/OCR/timing -- same boundary
    discipline as hud_reader, and it means the logic is unit-testable with
    no video (see test_route_artifacts.py).
  * Text-only + a JSON file: the simplest artifact type and the simplest
    thing that survives process exit, per the design doc's phasing. A real
    deployment swaps ArtifactStore's backend for a shared service without
    touching the drop/discover logic on top of it.
"""

import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import List, Optional


@dataclass
class Artifact:
    id: str
    route_id: str
    position_km: float
    kind: str        # "text" in this POC; "audio"/"photo" are future types
    payload: str     # the note text (later: a reference to stored media)
    author: str
    seq: int         # monotonic drop order -- stable key for FIFO pruning
    created_at: str  # ISO-8601 UTC, informational only


class ArtifactStore:
    """File-backed, route-namespaced artifact store.

    Persistence is the feature, so the store is the part that has to survive
    process exit. A plain JSON file does that with zero infrastructure.
    Artifacts are namespaced by ``route_id`` so different routes never mix.
    """

    def __init__(self, path: str):
        self.path = path
        self._artifacts: List[Artifact] = []
        self._next_seq = 0
        self._load()

    def _load(self) -> None:
        if not os.path.exists(self.path):
            return
        with open(self.path) as f:
            doc = json.load(f)
        self._artifacts = [Artifact(**a) for a in doc.get("artifacts", [])]
        # next_seq is persisted so ids stay unique across sessions even after
        # pruning removes earlier artifacts.
        self._next_seq = doc.get("next_seq", len(self._artifacts))

    def save(self) -> None:
        doc = {
            "next_seq": self._next_seq,
            "artifacts": [asdict(a) for a in self._artifacts],
        }
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        with open(self.path, "w") as f:
            json.dump(doc, f, indent=2)

    def drop(self, route_id: str, position_km: float, payload: str,
             author: str, kind: str = "text") -> Artifact:
        """Leave an artifact at a route position. Caller save()s to persist."""
        art = Artifact(
            id=f"{route_id}:{self._next_seq}",
            route_id=route_id,
            position_km=round(float(position_km), 3),
            kind=kind,
            payload=payload,
            author=author,
            seq=self._next_seq,
            created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        )
        self._artifacts.append(art)
        self._next_seq += 1
        return art

    def artifacts_for(self, route_id: str) -> List[Artifact]:
        """Every artifact on a route, sorted by position along the route."""
        return sorted((a for a in self._artifacts if a.route_id == route_id),
                      key=lambda a: a.position_km)

    def prune(self, route_id: str, max_count: int) -> int:
        """Keep only the newest ``max_count`` artifacts on a route (FIFO drop).

        Bounds storage so a popular route can't grow without limit. Oldest
        (smallest seq) go first -- the simplest policy; the design doc lists
        alternatives (age / least-viewed). Returns how many were removed.
        """
        on_route = [a for a in self._artifacts if a.route_id == route_id]
        if len(on_route) <= max_count:
            return 0
        keep = {a.seq for a in sorted(on_route, key=lambda a: a.seq)[-max_count:]}
        before = len(self._artifacts)
        self._artifacts = [a for a in self._artifacts
                           if a.route_id != route_id or a.seq in keep]
        return before - len(self._artifacts)


class ArtifactDiscoverer:
    """Fires each artifact once, as the rider's route position reaches it.

    Tracks a HIGH-WATER MARK of the furthest position reached, not just the
    latest reading. That makes discovery robust to the OCR position dipping
    on a bad frame: a backwards flicker never re-arms an already-passed
    artifact and never skips one. Same fire-once-on-crossing idea as
    demo_v1.py's km-milestone banner, generalized to arbitrary anchor points.

    The FIRST position fed in establishes where this session started;
    artifacts already behind that point can't be crossed by forward motion,
    so they're dropped from THIS session's consideration (they stay untouched
    in the store -- a rider who starts earlier will still find them).
    """

    def __init__(self, artifacts: List[Artifact], trigger_radius_km: float = 0.0):
        self._pending = sorted(artifacts, key=lambda a: a.position_km)
        self._radius = trigger_radius_km
        self._high_water: Optional[float] = None

    def advance(self, position_km: Optional[float]) -> List[Artifact]:
        """Feed the next route position; return artifacts newly crossed."""
        if position_km is None:
            return []  # unreadable frame -- hold, decide nothing

        if self._high_water is None:
            # First fix: baseline the session start. Anything already behind
            # us this session can never be reached going forward.
            self._high_water = position_km
            self._pending = [a for a in self._pending
                             if a.position_km - self._radius > position_km]
            return []

        if position_km <= self._high_water:
            return []  # no forward progress (or a backwards OCR flicker)

        self._high_water = position_km
        reached = [a for a in self._pending
                   if a.position_km - self._radius <= position_km]
        self._pending = [a for a in self._pending
                         if a.position_km - self._radius > position_km]
        return reached
