"""
record_audio.py -- capture a short voice clip from the mic via ffmpeg.

The record-a-message feature needs to turn "the rider held the button and spoke"
into a file on disk that a later session can play back at the same spot. We
already ship ffmpeg (imageio_ffmpeg's bundled binary, used by demo_experience),
and on Windows it can grab the mic directly through DirectShow (dshow) -- so no
new audio-capture dependency.

Recording runs in a BACKGROUND process (ffmpeg with a fixed ``-t`` duration), so
the ride loop never blocks for the length of the clip: we kick off the capture,
immediately drop the artifact at the rider's CURRENT position, and the file
materialises a few seconds later (well before the next session plays it).

The two fiddly bits -- discovering the mic's exact dshow name and assembling the
command -- are pure helpers (`parse_dshow_audio_devices`, `build_record_command`)
so they're unit-tested without spawning ffmpeg or needing a mic. Windows-only
(dshow); the rest of the pipeline is Windows anyway.
"""

import os
import re
import subprocess
import sys

try:
    import imageio_ffmpeg
    _FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
except Exception:  # pragma: no cover - fall back to PATH
    _FFMPEG = "ffmpeg"


def ffmpeg_exe():
    return _FFMPEG


def parse_dshow_audio_devices(stderr_text):
    """Pull audio device names out of ffmpeg's -list_devices output.

    ffmpeg prints device lines to STDERR, each ending in "(audio)" or "(video)"
    with the quoted name earlier on the line, e.g.:
        [dshow @ ...] "Microphone (Realtek Audio)" (audio)
    Returns the audio device names in listed order.
    """
    names = []
    for line in stderr_text.splitlines():
        if "(audio)" not in line:
            continue
        m = re.search(r'"([^"]+)"', line)
        if m:
            names.append(m.group(1))
    return names


def list_input_devices():
    """Live: ask ffmpeg for the machine's dshow audio input names."""
    if sys.platform != "win32":
        return []
    proc = subprocess.run(
        [_FFMPEG, "-hide_banner", "-list_devices", "true", "-f", "dshow", "-i", "dummy"],
        capture_output=True, text=True)
    # ffmpeg exits non-zero on the dummy input by design; parse stderr anyway.
    return parse_dshow_audio_devices(proc.stderr)


def build_record_command(device, out_path, seconds, *, ffmpeg=None):
    """Pure: the argv to capture ``seconds`` of ``device`` into ``out_path``.

    Passed as a list (no shell), so a device name with spaces/parens needs no
    quoting. Output codec follows the extension (.wav = PCM, .mp3 = libmp3lame).
    """
    return [
        ffmpeg or _FFMPEG, "-y",
        "-f", "dshow", "-i", f"audio={device}",
        "-t", str(seconds),
        "-ac", "1", "-ar", "44100",
        out_path,
    ]


def record(device, out_path, seconds, *, ffmpeg=None, log_path=None):
    """Start a background ffmpeg capture; return the Popen (non-blocking).

    Caller can drop the artifact immediately and let the file finish writing --
    but MUST wait for the process before exiting, or the OS kills ffmpeg
    mid-write and no file is finalised. ``log_path`` (recommended) captures
    ffmpeg's stderr so a failed capture is diagnosable instead of silent.

    A failed spawn returns None so the ride loop degrades gracefully (the
    artifact is still dropped, just silent).
    """
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    cmd = build_record_command(device, out_path, seconds, ffmpeg=ffmpeg)
    err = open(log_path, "wb") if log_path else subprocess.DEVNULL
    try:
        return subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=err,
                                stdin=subprocess.DEVNULL)
    except Exception as e:  # pragma: no cover - spawn failure is environment-specific
        print(f"[record] could not start ffmpeg: {e}")
        return None
