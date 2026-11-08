"""Tests for demo_voices/ filename parsing + placement in demo_audio_memories."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from demo_audio_memories import (  # noqa: E402
    load_demo_voices, parse_voice_filename, place_voices)


def test_metres_with_unit():
    assert parse_voice_filename("300m_alice_good-luck-on-finals.mp3") == \
        (0.3, "alice", "good luck on finals")


def test_bare_number_is_metres():
    assert parse_voice_filename("620_bob.wav") == (0.62, "bob", "")


def test_km_unit():
    pos, author, cap = parse_voice_filename("1.05km_carol_almost_home.ogg")
    assert abs(pos - 1.05) < 1e-9 and author == "carol" and cap == "almost home"


def test_no_position():
    assert parse_voice_filename("welcome.mp3") == (None, "welcome", "")


def test_unplaced_spaced_evenly_and_out_of_range_dropped():
    placed = place_voices([("a.mp3", None, "a", ""), ("b.mp3", None, "b", ""),
                           ("x.mp3", 0.5, "x", ""), ("far.mp3", 9.0, "far", "")],
                          total_km=1.2)
    assert [(fn, pos) for fn, pos, _, _ in placed] == \
        [("a.mp3", 0.4), ("x.mp3", 0.5), ("b.mp3", 0.8)]


def test_load_reads_only_audio_files(tmp_path):
    for n in ("300m_alice.mp3", "notes.txt", "README.md", "900_bob.WAV"):
        (tmp_path / n).write_bytes(b"")
    arts, captions = load_demo_voices(str(tmp_path))
    assert [(a.author, a.position_km, a.kind) for a in arts] == \
        [("alice", 0.3, "audio"), ("bob", 0.9, "audio")]
    assert len({a.id for a in arts}) == 2
    assert set(captions) == {a.payload for a in arts}


def test_missing_folder_is_empty(tmp_path):
    assert load_demo_voices(str(tmp_path / "nope")) == ([], {})
