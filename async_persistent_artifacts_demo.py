"""
async_persistent_artifacts_demo.py -- LIVE test of ASYNCHRONOUS, PERSISTENT
route artifacts: pedal, and press the gamepad to leave things behind for a
LATER rider to find.

While riding you press a gamepad button (the bike's own ABXY don't reach the PC,
so we use the borrowed Xbox pad):
    A (button 0) -> RECORD a short voice memory, pinned to your current spot
    1/2/3 buttons -> drop a preset "trinket" (Paws plushie / NU poster / shout-out)
Each is stored, pinned to the route position, and SURVIVES the session (that's
the "persistent" + "async" part). A later ride HEARS/finds them on pass-by via
    python route_artifacts_poc/demo_audio_memories.py --store <same store>

This is a thin launcher for route_artifacts_poc/demo_leave_message.py (the
"leave" engine) so it has an obvious top-level name for the rig. Gamepad events
work even with Rouvy focused (SDL background-events hint in input_trigger).

On the rig (record a voice memory needs the mic name):
    python async_persistent_artifacts_demo.py --live --region 1920,0,1920,1080 \
        --device "Microphone Array (2- Realtek(R) Audio)" --rider you

At a desk first (no bike; keyboard SPACE / 1 / 2 / 3 / Q also work):
    python async_persistent_artifacts_demo.py --simulate --reset \
        --device "Microphone Array (2- Realtek(R) Audio)"
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "route_artifacts_poc"))

from demo_leave_message import main  # noqa: E402

if __name__ == "__main__":
    main()
