"""
mic_check.py -- confirm a mic is actually CAPTURING sound (not just writing a
silent file). "A file appeared but there's no audio" almost always means the
wrong dshow input device, or a muted / permission-blocked mic. This records a
few seconds from each audio input and reports its volume level, so you can tell
a live mic from a dead one BEFORE trusting it for voice memories.

Speak (or tap the mic) while it records. Interpretation:
  * max_volume near -80/-90 dB  -> effectively SILENT (dead input / wrong device)
  * max_volume above ~ -30 dB    -> it's hearing you: GOOD

    python mic_check.py                 # test every input device
    python mic_check.py --device "Microphone Array (2- Realtek(R) Audio)"
    python mic_check.py --seconds 5

Once you know which name is live, pass it to demo_leave_message.py --device.
"""

import argparse
import os
import re
import subprocess
import tempfile

import record_audio

SILENCE_DB = -60.0   # peaks below this are basically no signal


def measure(device, seconds, ffmpeg):
    """Record `seconds` from `device`, return (mean_dB, max_dB) or (None, None)."""
    tmp = os.path.join(tempfile.gettempdir(), "mic_check.wav")
    subprocess.run(record_audio.build_record_command(device, tmp, seconds, ffmpeg=ffmpeg),
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                   stdin=subprocess.DEVNULL)
    if not (os.path.exists(tmp) and os.path.getsize(tmp) > 0):
        return None, None
    p = subprocess.run([ffmpeg, "-hide_banner", "-i", tmp, "-af", "volumedetect",
                        "-f", "null", "-"], capture_output=True, text=True)
    mean = re.search(r"mean_volume:\s*(-?[\d.]+) dB", p.stderr)
    peak = re.search(r"max_volume:\s*(-?[\d.]+) dB", p.stderr)
    return (float(mean.group(1)) if mean else None,
            float(peak.group(1)) if peak else None)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--device", default=None, help="one device (default: test all)")
    ap.add_argument("--seconds", type=float, default=4.0)
    args = ap.parse_args()

    ffmpeg = record_audio.ffmpeg_exe()
    devices = [args.device] if args.device else record_audio.list_input_devices()
    if not devices:
        raise SystemExit("No dshow audio input devices found.")

    print(f"Testing {len(devices)} device(s), {args.seconds:.0f}s each. "
          f"SPEAK while each one records.\n")
    for dev in devices:
        print(f"* {dev!r}\n  recording…", flush=True)
        mean, peak = measure(dev, args.seconds, ffmpeg)
        if peak is None:
            print("  no file / no audio stream -- device unavailable.\n")
            continue
        verdict = "GOOD (hearing you)" if peak > SILENCE_DB else "SILENT (dead / wrong device)"
        print(f"  mean={mean} dB  peak={peak} dB  -> {verdict}\n")


if __name__ == "__main__":
    main()
