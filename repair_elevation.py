"""
repair_elevation.py

A stream transform that repairs a SMOOTHLY-VARYING field (default
`max_elevation`) using temporal plausibility, for the frames OCR gets wrong
on moving video. It sits between stream_hud.py and any consumer, same JSONL
in/out shape as repair_stream.py:

    stream_hud.py ... | python repair_elevation.py | consumer

Why this is different from repair_stream.py: that repair uses the route-sum
INVARIANT (current + remaining = total). max_elevation has no such invariant
-- nothing algebraically constrains it. What we DO know (see CLAUDE.md) is
that it changes SLOWLY (98 -> 93 over the whole Brookline clip), while its OCR
errors are single-frame OUTLIERS: the bright elevation-profile peaks scroll
behind the digits and flip e.g. 93 -> 3, 95 -> 395, or drop to None.

So the repair is a robust temporal filter, NOT a clamp:
  * Keep a short window of recently ACCEPTED values; the reference is their
    MEDIAN (robust -- one bad value in the window can't move it).
  * A new reading is REJECTED if it's None, or deviates from that median by
    more than --max-jump; on reject we HOLD the last accepted value.
  * Otherwise it's ACCEPTED and joins the window, so the reference tracks the
    real slow drift (98 -> 93) instead of freezing.

This is deliberately NOT a monotonicity clamp: max_elevation DECREASES as the
rider advances (it tracks the peak of the remaining profile), so "non-
decreasing" would be wrong -- see the CLAUDE.md correction. Smoothness holds;
monotonicity does not.

Honesty / non-silence (a project convention, same as repair_stream.py):
  * Every repaired reading is MARKED -- the record gains a "repaired" key
    {field: {"from": <old>, "to": <new>}} -- so a held value is never silently
    mistaken for a real read.
  * A per-run count of repaired frames prints to stderr.

Bootstrap caveat: before the first acceptable reading there's nothing to hold,
so leading bad/None frames pass through unrepaired (honestly None), and the
first accepted value seeds the window -- if that first value were itself an
outlier the window would self-correct within a few frames as real values
outvote it in the median.

Usage:
    python repair_elevation.py --stream run.jsonl
    stream_hud.py --video v.mp4 --fps 2 | python repair_elevation.py --field max_elevation
"""

import argparse
import json
import statistics
import sys
from collections import deque
from typing import Optional


def load_stream(path: Optional[str]):
    f = open(path) if path else sys.stdin
    try:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)
    finally:
        if path:
            f.close()


def _as_number(value) -> Optional[float]:
    if isinstance(value, list) and len(value) == 2 and isinstance(value[0], (int, float)):
        return float(value[0])
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return None


def _unit_of(value, default: str) -> str:
    if isinstance(value, list) and len(value) == 2 and isinstance(value[1], str):
        unit = value[1].strip()
        if unit:
            return unit
    return default


class ElevationRepairer:
    """Temporal-plausibility repairer for one smoothly-varying field.

    Kept as a class (not a bare function) because the decision for each frame
    depends on state -- the window of accepted values and the last held value.
    That state is exactly what makes this testable on a plain number series
    with no video (see test), mirroring route_artifacts' discoverer.
    """

    def __init__(self, field: str, max_jump: float, window: int, default_unit: str):
        self.field = field
        self.max_jump = max_jump
        self.default_unit = default_unit
        self._accepted = deque(maxlen=window)
        self._last = None  # last accepted numeric value (what we hold)

    def process(self, record: dict) -> bool:
        """Repair the field in `record` in place. Returns True if repaired."""
        readings = record.get("readings", {})
        r = _as_number(readings.get(self.field))

        # Bootstrap: nothing trusted yet.
        if not self._accepted:
            if r is not None:
                self._accepted.append(r)
                self._last = r
            return False  # leading None/first value pass through untouched

        reference = statistics.median(self._accepted)
        accept = r is not None and abs(r - reference) <= self.max_jump

        if accept:
            self._accepted.append(r)
            self._last = r
            return False

        # Reject (None or an implausible jump): hold the last accepted value.
        old = readings.get(self.field)
        unit = _unit_of(old, self.default_unit)
        held = int(self._last) if float(self._last).is_integer() else self._last
        readings[self.field] = [held, unit]
        record.setdefault("repaired", {})[self.field] = {"from": old, "to": readings[self.field]}
        return True


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--stream", default=None, help="JSONL from stream_hud.py (default: stdin)")
    p.add_argument("--field", default="max_elevation", help="field to repair (default: max_elevation)")
    p.add_argument("--max-jump", type=float, default=8.0,
                   help="reject a reading deviating from the window median by more than this (default: 8)")
    p.add_argument("--window", type=int, default=7,
                   help="how many recent accepted values form the median reference (default: 7)")
    p.add_argument("--unit", default="m", help="unit for a held reading with no clean unit (default: m)")
    p.add_argument("--out", default=None, help="also write repaired JSONL here")
    args = p.parse_args()

    rep = ElevationRepairer(args.field, args.max_jump, args.window, args.unit)
    out_file = open(args.out, "w") if args.out else None
    repaired = total = 0
    try:
        for record in load_stream(args.stream):
            total += 1
            if rep.process(record):
                repaired += 1
            line = json.dumps(record)
            print(line, flush=True)
            if out_file is not None:
                out_file.write(line + "\n")
    finally:
        if out_file is not None:
            out_file.close()

    print(f"[repair_elevation] repaired {args.field} on {repaired}/{total} frame(s) "
          f"(max_jump={args.max_jump}, window={args.window}).", file=sys.stderr)


if __name__ == "__main__":
    main()
