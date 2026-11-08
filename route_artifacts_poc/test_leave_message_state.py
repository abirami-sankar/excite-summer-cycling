"""Tests for the pure ride-state + press-gating logic in demo_leave_message."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from demo_leave_message import (  # noqa: E402
    IDLE, PAUSED, PRERIDE, RIDING, accept_action, it, next_state, probe_for)


def test_probe_looks_for_preride_until_riding():
    assert probe_for(None) == "preride"
    assert probe_for(PRERIDE) == "preride"
    assert probe_for(IDLE) == "preride"
    assert probe_for(RIDING) == "pause"
    assert probe_for(PAUSED) == "pause"


def test_preride_dialog_wins():
    assert next_state(None, seen=True, riding_signal=True) == PRERIDE
    assert next_state(IDLE, seen=True, riding_signal=False) == PRERIDE


def test_pause_menu_from_riding():
    assert next_state(RIDING, seen=True, riding_signal=True) == PAUSED


def test_resume_from_pause_when_menu_gone():
    assert next_state(PAUSED, seen=False, riding_signal=True) == RIDING


def test_riding_vs_idle_follows_distance_signal():
    assert next_state(PRERIDE, seen=False, riding_signal=True) == RIDING
    assert next_state(RIDING, seen=False, riding_signal=False) == IDLE
    assert next_state(None, seen=False, riding_signal=False) == IDLE


def test_presses_only_accepted_while_riding():
    for s in (None, PRERIDE, PAUSED, IDLE):
        ok, _ = accept_action(it.LEAVE_MESSAGE, state=s, cur_km=0.3, recording=False)
        assert not ok
        ok, _ = accept_action(it.OPTION_1, state=s, cur_km=0.3, recording=False)
        assert not ok
    assert accept_action(it.LEAVE_MESSAGE, state=RIDING, cur_km=0.3, recording=False)[0]


def test_needs_a_position():
    ok, why = accept_action(it.LEAVE_MESSAGE, state=RIDING, cur_km=None, recording=False)
    assert not ok and "position" in why


def test_no_overlapping_recordings_but_trinkets_still_ok():
    ok, why = accept_action(it.LEAVE_MESSAGE, state=RIDING, cur_km=0.3, recording=True)
    assert not ok and "recording" in why
    assert accept_action(it.OPTION_2, state=RIDING, cur_km=0.3, recording=True)[0]
