"""
test_repair_elevation.py

Unit tests for the max_elevation temporal-plausibility repair
(repair_elevation.py). Pure logic: feed a number series as JSONL-shaped
records, assert the repaired series -- no video/OCR, mirroring
test_route_artifacts.py.
"""

from repair_elevation import ElevationRepairer


def _rec(v):
    # unit_value readings are [num, unit]; None means unreadable.
    return {"readings": {"max_elevation": None if v is None else [v, "m"]}}


def _run(values, max_jump=8.0, window=7):
    rep = ElevationRepairer("max_elevation", max_jump, window, "m")
    out = []
    for v in values:
        r = _rec(v)
        repaired = rep.process(r)
        val = r["readings"]["max_elevation"]
        out.append((val[0] if isinstance(val, list) else val, repaired))
    return out


def _vals(values, **kw):
    return [v for v, _ in _run(values, **kw)]


def test_single_frame_outlier_rejected_and_held():
    # 5 and 395 are wild outliers among a steady ~98
    assert _vals([98, 98, 5, 98, 395, 98]) == [98, 98, 98, 98, 98, 98]


def test_none_gaps_are_held():
    assert _vals([98, None, None, 98]) == [98, 98, 98, 98]


def test_slow_drift_is_tracked_not_frozen():
    # a real slow decline (<= max_jump per step) must pass through untouched
    assert _vals([98, 97, 96, 95, 94, 93]) == [98, 97, 96, 95, 94, 93]


def test_leading_bad_frames_pass_through_before_bootstrap():
    # nothing to hold yet -> honest None until the first acceptable read seeds
    assert _vals([None, None, 95]) == [None, None, 95]


def test_repaired_records_are_marked():
    rep = ElevationRepairer("max_elevation", 8.0, 7, "m")
    rep.process(_rec(98))          # seed
    good = _rec(98); assert rep.process(good) is False and "repaired" not in good
    bad = _rec(3)                  # outlier
    assert rep.process(bad) is True
    assert bad["repaired"]["max_elevation"]["from"] == [3, "m"]
    assert bad["repaired"]["max_elevation"]["to"] == [98, "m"]


def test_window_median_ignores_a_single_bad_seed():
    # if one stray value sneaks into the window, the median still tracks truth
    # so subsequent real values are accepted, not rejected against the stray
    out = _vals([98, 98, 98, 120, 98, 99])  # 120 rejected, 99 still accepted
    assert out == [98, 98, 98, 98, 98, 99]
