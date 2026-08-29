"""
verify_stream.py

Verifies a stream of parsed HUD readings (the JSONL emitted by
stream_hud.py) against what it *should* be. This is the time-ordered
counterpart to test_hud_reader.py, which only checks single static crops.

Two INDEPENDENT checks -- run either, or both:

  1. INVARIANT check (no hand-entered data needed).
     The route has a fixed total length, so on any frame where both
     distances read cleanly:

         current_distance + remaining_distance == ROUTE_TOTAL   (± tol)

     This catches OCR flicker for free -- e.g. remaining_distance
     misreading as 68.42 or 6.41 blows the sum far past 14.06 -- without
     anyone having to transcribe expected values frame by frame.

  2. EXPECTED check (needs an expected-values file, e.g. expected.json,
     shaped like expected_template.json).
     Per frame, per region, compares the stream's reading against a
     hand-entered expected value. A region set to null (or absent) on a
     frame is SKIPPED, so you can fill in only the frames/fields you've
     verified by eye.

The stream is read from a file (--stream) or stdin, so it composes with
stream_hud.py directly:

    python stream_hud.py --video data/training/trimmed-video.mp4 --end-time 5 --fps 2 \
        | python verify_stream.py --total 14.06

    python verify_stream.py --stream run.jsonl --total 14.06 \
        --expected configs/expected.json

Exit code is nonzero if any enabled check fails, so this is usable as a
gate in a test/CI step, not just a human-readable report.
"""

import argparse
import json
import sys
from typing import Optional


# The two unit_value fields whose readings must sum to the route total.
# Named here (not hard-coded in the check) so a different config could
# point the invariant at different field names without touching logic.
DISTANCE_FIELDS = ("current_distance", "remaining_distance")


def load_stream(path: Optional[str]) -> list:
    """Read JSONL records from a file, or from stdin if path is None."""
    f = open(path) if path else sys.stdin
    try:
        records = []
        for line_no, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as e:
                sys.exit(f"Bad JSON on stream line {line_no}: {e}")
        return records
    finally:
        if path:
            f.close()


def _as_number(value) -> Optional[float]:
    """Pull the numeric part out of a reading.

    A unit_value reading is a [number, unit] pair in JSON; a plain
    int/float reading is just the number. Anything else (None, a string,
    a malformed pair) yields None -- 'not a usable number here'.
    """
    if isinstance(value, list) and len(value) == 2 and isinstance(value[0], (int, float)):
        return float(value[0])
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return None


def _unit_of(value) -> Optional[str]:
    """The unit string of a unit_value reading, or None if it has none."""
    if isinstance(value, list) and len(value) == 2:
        return value[1]
    return None


# ---- Check 1: distance sum invariant -------------------------------------

def check_invariant(records: list, total: float, tol: float) -> dict:
    """Check current + remaining == total on every frame both read cleanly.

    Frames where either distance is missing/unreadable are reported as
    SKIPPED, not failed -- a None is an honest "couldn't read," which is
    a different problem from "read a wrong value that breaks the sum."
    """
    a_field, b_field = DISTANCE_FIELDS
    results = []
    for rec in records:
        t = rec.get("t")
        readings = rec.get("readings", {})
        a = _as_number(readings.get(a_field))
        b = _as_number(readings.get(b_field))

        if a is None or b is None:
            results.append({"t": t, "status": "SKIP",
                            "detail": f"{a_field}={readings.get(a_field)!r}, "
                                      f"{b_field}={readings.get(b_field)!r}"})
            continue

        got = a + b
        ok = abs(got - total) <= tol
        results.append({
            "t": t,
            "status": "PASS" if ok else "FAIL",
            "detail": f"{a:.2f} + {b:.2f} = {got:.2f} (expected {total:.2f} +/- {tol})",
        })
    return _summarize("Distance-sum invariant", results)


# ---- Check 2: comparison against hand-entered expected values -------------

def _values_match(got, expected, num_tol: float) -> bool:
    """Compare one region's stream reading to its expected value.

    unit_value -> both number (within num_tol) AND unit must match.
    int/float  -> number within num_tol.
    str        -> exact string match.
    """
    exp_num = _as_number(expected)
    if exp_num is not None:
        got_num = _as_number(got)
        if got_num is None or abs(got_num - exp_num) > num_tol:
            return False
        # For unit_value pairs, the unit has to match too.
        if _unit_of(expected) is not None:
            return _unit_of(got) == _unit_of(expected)
        return True
    # Non-numeric expected (a plain string): require exact equality.
    return got == expected


def check_expected(records: list, expected_path: str, num_tol: float) -> dict:
    """Compare each frame's readings to hand-entered expected values.

    Matching is by timestamp `t`. Regions set to null (or absent) in the
    expected file are skipped, so a partially-filled expected file only
    checks what you've actually verified.
    """
    with open(expected_path) as f:
        expected_doc = json.load(f)

    expected_by_t = {frame["t"]: frame.get("readings", {})
                     for frame in expected_doc.get("frames", [])}

    results = []
    for rec in records:
        t = rec.get("t")
        readings = rec.get("readings", {})
        exp_readings = expected_by_t.get(t)
        if exp_readings is None:
            results.append({"t": t, "status": "SKIP",
                            "detail": "no expected entry for this t"})
            continue

        mismatches = []
        checked = 0
        for name, exp_value in exp_readings.items():
            if exp_value is None:
                continue  # explicitly skipped for this frame
            checked += 1
            if not _values_match(readings.get(name), exp_value, num_tol):
                mismatches.append(f"{name}: got {readings.get(name)!r}, "
                                  f"expected {exp_value!r}")

        if checked == 0:
            results.append({"t": t, "status": "SKIP",
                            "detail": "all regions null for this t"})
        elif mismatches:
            results.append({"t": t, "status": "FAIL",
                            "detail": "; ".join(mismatches)})
        else:
            results.append({"t": t, "status": "PASS",
                            "detail": f"{checked} region(s) matched"})
    return _summarize("Expected-values check", results)


# ---- shared reporting -----------------------------------------------------

def _summarize(title: str, results: list) -> dict:
    passed = sum(1 for r in results if r["status"] == "PASS")
    failed = sum(1 for r in results if r["status"] == "FAIL")
    skipped = sum(1 for r in results if r["status"] == "SKIP")
    return {"title": title, "results": results,
            "passed": passed, "failed": failed, "skipped": skipped}


def print_report(report: dict) -> None:
    print(f"\n=== {report['title']} ===")
    for r in report["results"]:
        print(f"  [{r['status']}] t={r['t']}: {r['detail']}")
    print(f"  -> {report['passed']} passed, {report['failed']} failed, "
          f"{report['skipped']} skipped")


def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--stream", default=None,
                        help="JSONL file from stream_hud.py (default: read stdin)")
    parser.add_argument("--total", type=float, default=None,
                        help="Route total distance in km; enables the "
                             "current+remaining sum invariant check")
    parser.add_argument("--tol", type=float, default=0.05,
                        help="Tolerance (km) for the distance-sum invariant "
                             "(default: 0.05)")
    parser.add_argument("--expected", default=None,
                        help="Expected-values JSON (like expected_template.json); "
                             "enables the per-frame comparison check")
    parser.add_argument("--value-tol", type=float, default=0.01,
                        help="Numeric tolerance for the expected-values check "
                             "(default: 0.01)")
    args = parser.parse_args()

    if args.total is None and args.expected is None:
        sys.exit("Nothing to check: pass --total (invariant) and/or "
                 "--expected (hand-entered values).")

    records = load_stream(args.stream)
    if not records:
        sys.exit("No records read from stream.")

    reports = []
    if args.total is not None:
        reports.append(check_invariant(records, args.total, args.tol))
    if args.expected is not None:
        reports.append(check_expected(records, args.expected, args.value_tol))

    for report in reports:
        print_report(report)

    total_failed = sum(r["failed"] for r in reports)
    print(f"\nRead {len(records)} frame(s). "
          f"{'FAILURES PRESENT' if total_failed else 'All enabled checks passed.'}")
    sys.exit(1 if total_failed else 0)


if __name__ == "__main__":
    main()
