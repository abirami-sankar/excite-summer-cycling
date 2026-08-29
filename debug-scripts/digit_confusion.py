import os as _os, sys as _sys  # handoff: allow running from debug-scripts/
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))

"""
digit_confusion.py

Builds a position-aware digit-vs-digit confusion matrix for numeric HUD
fields, so "the leading 8 flickers to 6" stops being an anecdote and
becomes counts you can point at.

For each frame it aligns the OCR reading against a known-correct value
digit by digit (anchored on the decimal point, integer part right-
justified, fraction part left-justified) and tallies three kinds of
error per place value:

    * SUBSTITUTION -- expected digit d1 read as a different digit d2
    * PHANTOM      -- a digit appeared where none was expected
                      (the extra leading '6' in 68.42)
    * DROPPED      -- an expected digit went missing

IMPORTANT -- this is a DIAGNOSTIC, not a corrector. Unlike
hud_reader._fix_confusable_digits (which safely remaps LETTERS to digits,
because a letter in a number is always wrong), you CANNOT blindly remap
6 -> 8: 6 is a legitimate digit, so a blanket remap would corrupt every
real 6. Use this matrix to LOCATE the weak digit/place, then fix it via
preprocessing (crop/threshold -- see how the remaining_distance box was
tightened) or the invariant repair (repair_stream.py) -- never a digit
lookup table. See CLAUDE.md.

Ground truth comes from ONE of:

    --expected FILE      hand-entered expected values, shaped like
                         expected_template.json (null / absent = skip).

    --invariant A,B,T    derive truth from the sum invariant with ZERO
                         manual labels: A is the TRUSTED anchor field, B is
                         the field being profiled, and they must sum to T,
                         so true B = T - A. Perfect for profiling
                         remaining_distance against the reliable
                         current_distance and the 14.06 km route total.
                         (Only one direction -- a wrong B must not be used
                         to "derive" A's truth, or every real error in B
                         would fabricate a bogus error in A.)

Stream input: --stream FILE, or stdin (the JSONL from stream_hud.py).

Usage:
    # Profile remaining_distance using the route-total invariant, no labels:
    python stream_hud.py --video data/training/trimmed-video.mp4 --end-time 30 --fps 2 \
        | python digit_confusion.py --invariant current_distance,remaining_distance,14.06

    # Profile against a hand-entered expected file:
    python digit_confusion.py --stream run.jsonl --expected configs/expected.json
"""

import argparse
import json
import sys
from collections import Counter, defaultdict
from typing import Optional

NONE = "."  # symbol for "no digit here" (phantom / dropped) in the matrix


def load_stream(path: Optional[str]) -> list:
    f = open(path) if path else sys.stdin
    try:
        return [json.loads(line) for line in f if line.strip()]
    finally:
        if path:
            f.close()


def _as_number(value) -> Optional[float]:
    """Numeric part of a reading: [num, unit] pair, or a bare int/float."""
    if isinstance(value, list) and len(value) == 2 and isinstance(value[0], (int, float)):
        return float(value[0])
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return None


def _place_label(power: int) -> str:
    """Human label for a base-10 place, e.g. 0->'ones', -1->'tenths'."""
    names = {2: "hundreds", 1: "tens", 0: "ones",
             -1: "tenths", -2: "hundredths", -3: "thousandths"}
    return names.get(power, f"10^{power}")


def align_digits(expected: str, got: str):
    """Align two formatted numeric strings and yield per-place comparisons.

    Integer parts are right-justified and fraction parts left-justified,
    both anchored on the decimal point, so the same place value lines up
    even when the strings differ in length (that's what surfaces a phantom
    LEADING digit as a phantom, not a shift of every column).

    Yields dicts: {place, label, leading, exp, got} where exp/got are a
    single digit char or None (meaning "no digit at this place").
    """
    def split(s):
        return s.split(".", 1) if "." in s else (s, "")

    e_int, e_frac = split(expected)
    g_int, g_frac = split(got)

    # Integer: right-justify (pad on the LEFT), so ones line up with ones.
    w_int = max(len(e_int), len(g_int))
    e_int_p, g_int_p = e_int.rjust(w_int), g_int.rjust(w_int)
    for k in range(w_int):
        power = w_int - 1 - k
        e_c = e_int_p[k] if e_int_p[k] != " " else None
        g_c = g_int_p[k] if g_int_p[k] != " " else None
        yield {"place": power, "label": _place_label(power),
               "leading": k == 0, "exp": e_c, "got": g_c}

    # Fraction: left-justify (pad on the RIGHT), so tenths line up with tenths.
    w_frac = max(len(e_frac), len(g_frac))
    e_frac_p, g_frac_p = e_frac.ljust(w_frac), g_frac.ljust(w_frac)
    for k in range(w_frac):
        power = -(k + 1)
        e_c = e_frac_p[k] if e_frac_p[k] != " " else None
        g_c = g_frac_p[k] if g_frac_p[k] != " " else None
        yield {"place": power, "label": _place_label(power),
               "leading": False, "exp": e_c, "got": g_c}


class ConfusionTally:
    def __init__(self):
        self.matrix = defaultdict(Counter)     # matrix[expected][got] = count
        self.by_place = Counter()              # place label -> error count
        self.leading_errors = 0
        self.leading_total = 0
        self.correct = 0
        self.total = 0
        self.examples = []                     # (t, field, expected, got)

    def add(self, t, field, expected_num: float, got_num: float, decimals: int):
        exp_s = f"{expected_num:.{decimals}f}"
        got_s = f"{got_num:.{decimals}f}"
        mismatched = False
        for cell in align_digits(exp_s, got_s):
            e, g = cell["exp"], cell["got"]
            self.total += 1
            if cell["leading"]:
                self.leading_total += 1
            if e == g:
                self.correct += 1
                continue
            mismatched = True
            self.matrix[e or NONE][g or NONE] += 1
            self.by_place[cell["label"]] += 1
            if cell["leading"]:
                self.leading_errors += 1
        if mismatched:
            self.examples.append((t, field, exp_s, got_s))

    def report(self):
        print("\n=== Digit confusion matrix (rows=expected, cols=read) ===")
        digits = [str(d) for d in range(10)] + [NONE]
        seen_rows = [d for d in digits if self.matrix.get(d)]
        if not seen_rows:
            print("  (no digit-level errors -- every aligned digit matched)")
        else:
            header = "exp\\got |" + "".join(f"{d:>4}" for d in digits)
            print("  " + header)
            print("  " + "-" * len(header))
            for r in seen_rows:
                row = f"{r:>7} |" + "".join(f"{self.matrix[r].get(c, 0) or '.':>4}" for c in digits)
                print("  " + row)
            print(f"  ('{NONE}' row = DROPPED digit, '{NONE}' column = PHANTOM digit)")

        print("\n--- Top confusions ---")
        flat = [((e, g), n) for e, row in self.matrix.items() for g, n in row.items()]
        for (e, g), n in sorted(flat, key=lambda x: -x[1])[:8]:
            kind = ("phantom" if e == NONE else "dropped" if g == NONE else "substitution")
            print(f"  {e} -> {g}  x{n}   ({kind})")

        print("\n--- Errors by place value ---")
        for label, n in self.by_place.most_common():
            print(f"  {label:<12} {n}")
        if self.leading_total:
            rate = 100 * self.leading_errors / self.leading_total
            print(f"  leading-digit error rate: {self.leading_errors}/{self.leading_total} "
                  f"({rate:.0f}%)")

        acc = 100 * self.correct / self.total if self.total else 0
        print(f"\n--- Summary ---")
        print(f"  {self.correct}/{self.total} aligned digits correct ({acc:.1f}%) "
              f"across {len(self.examples)} misread frame(s)")
        if self.examples:
            print("  Misread frames:")
            for t, field, exp_s, got_s in self.examples:
                print(f"    t={t} {field}: expected {exp_s}, read {got_s}")


def truth_from_expected(records, expected_path):
    """Yield (t, field, expected_num, got_num) from a hand-entered file."""
    with open(expected_path) as f:
        doc = json.load(f)
    exp_by_t = {fr["t"]: fr.get("readings", {}) for fr in doc.get("frames", [])}
    for rec in records:
        t = rec.get("t")
        exp_readings = exp_by_t.get(t)
        if not exp_readings:
            continue
        got_readings = rec.get("readings", {})
        for field, exp_val in exp_readings.items():
            exp_num = _as_number(exp_val)
            got_num = _as_number(got_readings.get(field))
            if exp_num is not None and got_num is not None:
                yield (t, field, exp_num, got_num)


def truth_from_invariant(records, anchor, profiled, total, tol):
    """Yield (t, profiled, expected_num, got_num) using anchor+profiled==total.

    Only ONE direction: the trusted `anchor` defines the `profiled` field's
    true value (true = total - anchor). We deliberately do NOT also derive
    the anchor's truth from the profiled field -- if `profiled` is the one
    misreading (the whole reason we're profiling it), feeding it back would
    fabricate a matching error in the anchor. See the module docstring.

    Skips frames where either field is unreadable (a None is a read
    failure, not a digit misread), where the derived truth is implausible
    (negative, meaning the anchor was garbage), or where the sum already
    holds within `tol`. That last skip matters: anchor and profiled tick at
    slightly different sub-frame instants, so invariant-derived truth is
    only exact to ~one hundredths place -- counting sub-tolerance
    disagreements would fill the matrix with rounding jitter instead of
    real misreads. If the sum checks out, the read is trusted as correct.
    """
    for rec in records:
        t = rec.get("t")
        readings = rec.get("readings", {})
        a = _as_number(readings.get(anchor))
        b = _as_number(readings.get(profiled))
        if a is None or b is None:
            continue
        if abs(a + b - total) <= tol:
            continue  # sum holds -> trustworthy read, not a digit error
        expected_b = round(total - a, 2)
        if expected_b < 0:
            continue
        yield (t, profiled, expected_b, b)


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--stream", default=None,
                        help="JSONL from stream_hud.py (default: stdin)")
    parser.add_argument("--expected", default=None,
                        help="Hand-entered expected values (expected_template shape)")
    parser.add_argument("--invariant", default=None, metavar="ANCHOR,PROFILED,TOTAL",
                        help="Derive truth from the sum invariant: trusted ANCHOR "
                             "field, PROFILED field, and their TOTAL "
                             "(e.g. current_distance,remaining_distance,14.06)")
    parser.add_argument("--decimals", type=int, default=2,
                        help="Decimal places to align numbers at (default: 2, for km distances)")
    parser.add_argument("--tol", type=float, default=0.05,
                        help="Invariant tolerance (km): frames whose sum holds within "
                             "this are trusted (skipped), not profiled (default: 0.05)")
    args = parser.parse_args()

    if not args.expected and not args.invariant:
        sys.exit("Need a ground-truth source: --expected FILE or --invariant A,B,T")

    records = load_stream(args.stream)
    if not records:
        sys.exit("No records read from stream.")

    tally = ConfusionTally()

    if args.invariant:
        try:
            a, b, t_str = args.invariant.split(",")
            total = float(t_str)
        except ValueError:
            sys.exit("--invariant must look like: fieldA,fieldB,TOTAL")
        for t, field, exp_num, got_num in truth_from_invariant(records, a, b, total, args.tol):
            tally.add(t, field, exp_num, got_num, args.decimals)

    if args.expected:
        for t, field, exp_num, got_num in truth_from_expected(records, args.expected):
            tally.add(t, field, exp_num, got_num, args.decimals)

    tally.report()


if __name__ == "__main__":
    main()
