"""
test_record_audio.py

Unit tests for the pure helpers in record_audio: parsing ffmpeg's device dump
and assembling the capture command. No ffmpeg spawn, no microphone -- those are
the parts that need the live machine (and the rig).
"""

from record_audio import build_record_command, parse_dshow_audio_devices

# a trimmed but realistic slice of ffmpeg -list_devices stderr on Windows
_FFMPEG_DUMP = r'''
[dshow @ 000] DirectShow video devices (some may be both video and audio)
[dshow @ 000]  "HD WebCam"
[dshow @ 000]     Alternative name "@device_pnp_\\?\usb#..."
[dshow @ 000] DirectShow audio devices
[dshow @ 000]  "Microphone (Realtek(R) Audio)" (audio)
[dshow @ 000]  "Line In (Realtek(R) Audio)" (audio)
'''


def test_parse_lists_audio_devices_in_order():
    assert parse_dshow_audio_devices(_FFMPEG_DUMP) == [
        "Microphone (Realtek(R) Audio)",
        "Line In (Realtek(R) Audio)",
    ]


def test_parse_ignores_video_devices():
    assert "HD WebCam" not in parse_dshow_audio_devices(_FFMPEG_DUMP)


def test_parse_empty_when_no_audio():
    assert parse_dshow_audio_devices("no devices here") == []


def test_build_command_embeds_device_duration_and_output():
    cmd = build_record_command("Microphone (Realtek(R) Audio)",
                               "out/msg.mp3", 5, ffmpeg="FF")
    assert cmd[0] == "FF"
    # the device name is a single argv element (no shell quoting needed)
    assert "audio=Microphone (Realtek(R) Audio)" in cmd
    assert "-t" in cmd and cmd[cmd.index("-t") + 1] == "5"
    assert cmd[-1] == "out/msg.mp3"


def test_build_command_output_extension_drives_codec_choice():
    # we rely on ffmpeg picking the encoder from the extension, so the
    # extension must survive into the command untouched
    assert build_record_command("Mic", "a/b/clip.wav", 3)[-1] == "a/b/clip.wav"
