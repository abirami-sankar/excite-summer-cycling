"""
summarize_live_run.py

DIAGNOSTIC: quick-feedback summary for a stream_hud.py --live JSONL run.
Built for stress-testing the live capture path against recorded clips
before the campus test -- reading raw JSONL by eye doesn't scale once
you're running several stress tests back to back.

For each field, reports:
    - total records
    - how many were None (unreadable)
    - whether every non-None value was IDENTICAL across the whole run --
      this is the exact signature of the frozen/static-capture bug you
      hit with WMP exclusive fullscreen (same wrong value 15 times in a
      row). A real live feed of a MOVING video should not produce this,
      so it's flagged as a hard warning, not just a stat.
    - for numeric-ish fields (int/float, or the number half of a
      unit_value [num, unit] pair): min/max observed, as a cheap
      plausibility check (e.g. speed swinging from 5 to 400 in one run
      is a red flag worth a second look, same spirit as expected.json's
      plausibility-over-exact-match approach).

Does NOT require ground truth / expected.json -- this is a fast sanity
pass, not a substitute for verify_stream.py's real accuracy check. Use
this first (seconds), reach for verify_stream.py when you want to
actually measure correctness against known values.

Usage:
    python summarize_live_run.py --stream campus_live.jsonl
"""

import argparse
import json
import sys


def _numeric_part(value):
    """Pull a comparable number out of int/float/[num, unit]/None."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, list) and len(value) == 2 and isinstance(value[0], (int, float)):
        return value[0]
    return None  # str fields etc. -- not numeric, skip range check


def summarize(path):
    per_field = {}  # name -> list of raw values, in order, including None

    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            readings = record.get("readings", {})
            for name, value in readings.items():
                per_field.setdefault(name, []).append(value)

    if not per_field:
        sys.exit(f"No readings found in {path} -- is the file empty or malformed?")

    total = len(next(iter(per_field.values())))
    print(f"{path}: {total} records\n")

    header = f"{'field':<20} {'none':>6} {'%none':>7}  {'range (min..max)':<20}  flag"
    print(header)
    print("-" * len(header))

    for name, values in per_field.items():
        none_count = sum(1 for v in values if v is None)
        pct_none = 100 * none_count / len(values)

        non_none = [v for v in values if v is not None]
        numeric = [n for n in (_numeric_part(v) for v in non_none) if n is not None]

        if numeric:
            rng = f"{min(numeric)}..{max(numeric)}"
        else:
            rng = "-"

        flag = ""
        if non_none:
            # Compare by repr so int/float/list values all compare cleanly.
            distinct = {repr(v) for v in non_none}
            if len(distinct) == 1:
                flag = "STATIC -- same value every frame, check capture source"

        print(f"{name:<20} {none_count:>6} {pct_none:>6.0f}%  {rng:<20}  {flag}")

    print(
        "\nA field showing STATIC across a run of a MOVING video/ride means "
        "the capture is likely frozen on one frame (e.g. exclusive-fullscreen "
        "player blocking the screen grab) -- fix capture before touching OCR."
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--stream", required=True, help="Path to a stream_hud.py JSONL output file")
    args = parser.parse_args()
    summarize(args.stream)


if __name__ == "__main__":
    main()