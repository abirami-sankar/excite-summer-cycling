"""
test_audio_bed.py

Unit tests for the multi-channel audio manager (audio_bed.py). We drive a REAL
pygame mixer through SDL's "dummy" audio driver (set before pygame loads), so
these run headless with no speakers -- the same silent-machine path production
falls back to, exercised deterministically.

The layering/stop assertions use looping clips so a channel is guaranteed busy
for the duration of the check (no timing race). One test covers auto-reaping of
a finished one-shot, which is inherently time-based and so is bounded-polled.
"""

import math
import os
import struct
import time
import wave

os.environ.setdefault("SDL_AUDIODRIVER", "dummy")  # must precede pygame import

import pytest

from audio_bed import AudioBed, PYGAME_AVAILABLE

pytestmark = pytest.mark.skipif(not PYGAME_AVAILABLE, reason="pygame not installed")


def _write_tone(path, secs=0.15, freq=440, rate=44100):
    n = int(secs * rate)
    with wave.open(str(path), "w") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"".join(
            struct.pack("<h", int(32767 * 0.2 * math.sin(2 * math.pi * freq * i / rate)))
            for i in range(n)))


@pytest.fixture(scope="module")
def clip(tmp_path_factory):
    p = tmp_path_factory.mktemp("clips") / "tone.wav"
    _write_tone(p)
    return str(p)


@pytest.fixture
def bed():
    b = AudioBed(num_channels=8)
    if not b.available:
        pytest.skip("no audio mixer available even with the dummy driver")
    yield b
    b.close()


def test_play_tracks_and_sounds(bed, clip):
    assert bed.play("a", clip, loop=True) is True
    assert "a" in bed.active_clips()
    assert bed.is_playing("a")


def test_layers_multiple_clips_on_distinct_channels(bed, clip):
    bed.play("bed", clip, loop=True)
    bed.play("voice", clip, loop=True)
    assert bed.active_clips() == {"bed", "voice"}
    # two managed clips must not share one channel, or one would cut the other
    chans = {id(bed._active["bed"]), id(bed._active["voice"])}
    assert len(chans) == 2


def test_stop_one_leaves_the_others(bed, clip):
    bed.play("a", clip, loop=True)
    bed.play("b", clip, loop=True)
    bed.stop("a")
    assert bed.active_clips() == {"b"}
    assert not bed.is_playing("a")
    assert bed.is_playing("b")


def test_replaying_same_id_keeps_one_channel(bed, clip):
    bed.play("a", clip, loop=True)
    first = bed._active["a"]
    bed.play("a", clip, loop=True)   # restart, not a second layer
    assert bed.active_clips() == {"a"}
    assert first not in [c for k, c in bed._active.items() if k != "a"]


def test_stop_all(bed, clip):
    bed.play("a", clip, loop=True)
    bed.play("b", clip, loop=True)
    bed.stop_all()
    assert bed.active_clips() == set()


def test_volume_is_clamped(bed, clip):
    bed.play("a", clip, loop=True, volume=0.5)
    assert bed.get_volume("a") == pytest.approx(0.5, abs=0.02)
    bed.set_volume("a", 9.0)
    assert bed.get_volume("a") == pytest.approx(1.0, abs=0.02)
    bed.set_volume("a", -3.0)
    assert bed.get_volume("a") == pytest.approx(0.0, abs=0.02)


def test_unavailable_bed_is_safe_noop(clip):
    b = AudioBed(num_channels=4)
    if not b.available:
        pytest.skip("mixer unavailable; degradation path is the live case")
    b.available = False   # simulate a machine with no audio device
    assert b.play("a", clip) is False
    b.stop("a")           # no error
    b.set_volume("a", 1.0)
    assert b.is_playing("a") is False
    assert b.active_clips() == set()


def test_update_reaps_finished_oneshot(bed, clip):
    bed.play("a", clip, loop=False)   # ~0.15s one-shot
    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline:
        bed.update()
        if "a" not in bed.active_clips():
            break
        time.sleep(0.05)
    assert "a" not in bed.active_clips()
