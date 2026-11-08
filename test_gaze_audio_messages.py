"""Tests for the pure playback/lap logic in gaze_audio_messages_demo."""

import csv

from gaze_audio_messages_demo import ClipScheduler, EventLog, is_new_lap
from route_artifacts import Artifact


def _clip(name, km):
    return Artifact(id=f"demo_voices:{name}", route_id="campus-loop", position_km=km,
                    kind="audio", payload=f"/v/{name}.mp3", author=name, seq=0,
                    created_at="")


def _cmds(out):
    return [(c, a.author, r) for c, a, r in out]


def _sched(*clips):
    # no trigger radius -> positions in the tests read exactly
    s = ClipScheduler(list(clips), radius_km=0.0, pass_km=0.10)
    s.tick(0.0, riding=True, recording=False)        # baseline the session start
    return s


# ---- laps -------------------------------------------------------------------

def test_lap_wrap_detected():
    assert is_new_lap(1.33, 0.01)
    assert is_new_lap(0.70, 0.05)          # Rouvy restarted the route mid-ride


def test_no_lap_on_jitter_or_missing_reads():
    assert not is_new_lap(0.50, 0.48)      # small backwards OCR flicker
    assert not is_new_lap(1.33, 0.60)      # big drop but not near the start
    assert not is_new_lap(None, 0.01)
    assert not is_new_lap(1.33, None)


# ---- playback ---------------------------------------------------------------

def test_plays_on_reach_and_stops_once_past():
    s = _sched(_clip("alice", 0.30))
    assert _cmds(s.tick(0.31, riding=True, recording=False)) == [("play", "alice", "")]
    assert s.tick(0.35, riding=True, recording=False) == []
    assert _cmds(s.tick(0.41, riding=True, recording=False)) == [("stop", "alice", "passed")]


def test_record_ducks_playing_clips():
    s = _sched(_clip("alice", 0.30))
    s.tick(0.31, riding=True, recording=False)
    assert _cmds(s.start_recording()) == [("stop", "alice", "recording")]
    assert s.playing == {}


def test_clip_reached_while_recording_is_held_then_played():
    s = _sched(_clip("bob", 0.50))
    assert _cmds(s.tick(0.51, riding=True, recording=True)) == [("hold", "bob", "recording")]
    assert _cmds(s.tick(0.55, riding=True, recording=False)) == [("play", "bob", "")]


def test_held_clip_skipped_if_rode_past_during_recording():
    s = _sched(_clip("bob", 0.50))
    s.tick(0.51, riding=True, recording=True)
    assert _cmds(s.tick(0.65, riding=True, recording=False)) == \
        [("skip", "bob", "passed while recording")]


def test_pause_stops_playback_but_keeps_held_clips():
    s = _sched(_clip("alice", 0.30), _clip("bob", 0.32))
    s.tick(0.31, riding=True, recording=False)               # alice plays
    s.tick(0.33, riding=True, recording=True)                # bob held
    assert _cmds(s.tick(0.33, riding=False, recording=False)) == \
        [("stop", "alice", "paused")]
    # nothing starts while paused
    assert s.tick(0.34, riding=False, recording=False) == []
    # resume: bob still in range -> plays
    assert ("play", "bob", "") in _cmds(s.tick(0.34, riding=True, recording=False))


def test_reset_rearms_every_clip_for_the_next_lap():
    a = _clip("alice", 0.30)
    s = _sched(a)
    s.tick(0.31, riding=True, recording=False)
    assert _cmds(s.reset([a], "lap")) == [("stop", "alice", "lap")]
    s.tick(0.01, riding=True, recording=False)               # new lap baseline
    assert _cmds(s.tick(0.31, riding=True, recording=False)) == [("play", "alice", "")]


def test_finished_clip_reported_once():
    s = _sched(_clip("alice", 0.30))
    s.tick(0.31, riding=True, recording=False)
    assert _cmds(s.finished("demo_voices:alice")) == [("end", "alice", "")]
    assert s.finished("demo_voices:alice") == []


# ---- log --------------------------------------------------------------------

def test_event_log_writes_rows(tmp_path):
    p = tmp_path / "log.csv"
    log = EventLog(str(p))
    log.log("clip_start", state="RIDING", lap=2, km=0.3, clip="x.mp3", author="a")
    log.log("state", state="PAUSED", lap=2, km=None, detail="PAUSED")
    log.close()
    rows = list(csv.DictReader(open(p, encoding="utf-8")))
    assert [r["event"] for r in rows] == ["clip_start", "state"]
    assert rows[0]["position_m"] == "300" and rows[1]["position_m"] == ""
    assert float(rows[0]["unix_time"]) > 1e9
