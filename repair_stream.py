"""
repair_stream.py

A stream transform that repairs the `remaining_distance` reading using the
route-total invariant, for the frames OCR still gets wrong after the crop
fix. It sits BETWEEN stream_hud.py and any consumer, reading the JSONL
stream and emitting the same JSONL shape with bad values corrected:

    stream_hud.py ... | python repair_stream.py --total 14.06 | consumer

The invariant is: on this route, for every frame,

    current_distance + remaining_distance == TOTAL   (14.06 km)

So when the sum is off by more than --tol, at least one field is wrong.
We trust `current_distance` as the ANCHOR (it reads reliably -- it has no
elevation-graphic band over it, unlike remaining_distance did) and
reconstruct the other:

    remaining_distance := TOTAL - current_distance

Why current is the anchor and not a vote: this is a documented assumption,
not a proof. If a frame's current_distance is itself wrong, the repair
propagates that error into remaining_distance. That's an acceptable trade
here because current_distance validated as reliable across the clip -- but
it's the one thing to revisit if repairs ever look wrong.

Honesty / non-silence (a project convention):
  * Every repaired reading is MARKED -- the record gains a "repaired" key
    recording {field: {"from": <old>, "to": <new>}}, so a reconstructed
    value is never silently indistinguishable from a real OCR read.
  * A per-run summary of how many frames were repaired is printed to stderr.

Circularity warning: do NOT then re-run verify_stream.py's sum invariant
on repaired output and call it "verified" -- the repair FORCES the sum to
hold, so that check becomes trivially true. Repair quality can only be
judged against INDEPENDENT truth (hand-entered expected values, or eyeing
the frames), not the invariant it was built from.

The emitted format is otherwise identical to stream_hud.py's, preserving
"swap in a live source with no consumer changes."

Usage:
    python repair_stream.py --stream run.jsonl --total 14.06
    stream_hud.py --video v.mp4 --fps 2 | python repair_stream.py --total 14.06 --out fixed.jsonl
"""

import argparse
import json
import sys
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
    """Reuse the reading's existing unit if it has one, else a default."""
    if isinstance(value, list) and len(value) == 2 and isinstance(value[1], str):
        # Keep only a clean unit; a dirty OCR unit (e.g. "km :") falls back.
        unit = value[1].strip()
        if unit:
            return unit
    return default


def repair_record(record: dict, anchor: str, field: str, total: float,
                  tol: float, default_unit: str) -> bool:
    """Repair `field` from `anchor` in place if the invariant is violated.

    Returns True if a repair was made. A repair happens when the anchor
    reads cleanly AND the profiled field is either unreadable or breaks the
    sum by more than tol. Leaves everything untouched otherwise (including
    the honest None of a truly unreadable frame with no usable anchor).
    """
    readings = record.get("readings", {})
    a = _as_number(readings.get(anchor))
    if a is None:
        return False  # no trustworthy anchor -> nothing to reconstruct from

    b = _as_number(readings.get(field))
    sum_ok = b is not None and abs(a + b - total) <= tol
    if sum_ok:
        return False  # invariant holds -> the read is trusted, leave it

    expected_b = round(total - a, 2)
    if expected_b < 0:
        return False  # anchor itself is implausible -> don't fabricate

    old = readings.get(field)
    unit = _unit_of(old, default_unit)
    readings[field] = [expected_b, unit]
    record.setdefault("repaired", {})[field] = {"from": old, "to": readings[field]}
    return True


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--stream", default=None,
                        help="JSONL from stream_hud.py (default: read stdin)")
    parser.add_argument("--total", type=float, required=True,
                        help="Route total distance in km (e.g. 14.06)")
    parser.add_argument("--anchor", default="current_distance",
                        help="Trusted field used to reconstruct (default: current_distance)")
    parser.add_argument("--field", default="remaining_distance",
                        help="Field to repair (default: remaining_distance)")
    parser.add_argument("--tol", type=float, default=0.05,
                        help="Sum tolerance in km before a frame is repaired (default: 0.05)")
    parser.add_argument("--unit", default="km",
                        help="Unit to use when the repaired reading has no clean unit (default: km)")
    parser.add_argument("--out", default=None,
                        help="Optional path to also write the repaired JSONL to")
    args = parser.parse_args()

    out_file = open(args.out, "w") if args.out else None
    repaired = total = 0
    try:
        for record in load_stream(args.stream):
            total += 1
            if repair_record(record, args.anchor, args.field, args.total,
                             args.tol, args.unit):
                repaired += 1
            line = json.dumps(record)
            print(line, flush=True)
            if out_file is not None:
                out_file.write(line + "\n")
    finally:
        if out_file is not None:
            out_file.close()

    print(f"[repair_stream] repaired {args.field} on {repaired}/{total} frame(s) "
          f"via {args.anchor} and total={args.total}.", file=sys.stderr)


if __name__ == "__main__":
    main()
