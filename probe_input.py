"""
probe_input.py -- discover what the bike's buttons look like to THIS computer.

Before the wrapper can let a rider "press a button to leave a message", we have
to know whether the bike's ABXY buttons even reach this PC as input -- or whether
they're consumed privately by Rouvy/Zwift over Bluetooth, in which case the
wrapper can NEVER see them and we trigger from a keyboard/USB clicker instead.

Run it, put the bike in your hands, and mash the ABXY buttons:

  * Buttons/axes PRINT here  -> they're an OS-visible gamepad/HID. BEST case:
    the wrapper can read them directly, independently of Rouvy.
  * NOTHING prints here, but the buttons DO things inside Rouvy/Zwift
    -> they pair straight into the app over BLE. The wrapper can't see them;
    use a keyboard hotkey or a separate clicker as the trigger.
  * NOTHING prints anywhere (not here, not in the app) -> the app doesn't map
    them. That's the likely reason they "do nothing" today.

Cross-check: Win+R -> `joy.cpl` ("Set up USB game controllers"). If the bike
shows up there, it's an OS gamepad and this probe will see it too.

No new dependencies -- uses pygame (already installed). A tiny window is opened
only because SDL needs its event loop running to deliver controller events;
keep that window focused while you press.

    python probe_input.py
"""

import os
# also catch a gamepad that only reports while our window is in the background
os.environ.setdefault("SDL_JOYSTICK_ALLOW_BACKGROUND_EVENTS", "1")

import pygame


def main():
    pygame.init()
    pygame.joystick.init()
    # SDL delivers joystick/controller events only while its event pump runs,
    # which needs the video subsystem up -- hence a small (focused) window.
    screen = pygame.display.set_mode((420, 120))
    pygame.display.set_caption("input probe - press the bike's ABXY buttons")

    sticks = [pygame.joystick.Joystick(i) for i in range(pygame.joystick.get_count())]
    for s in sticks:
        s.init()
        print(f"[device] #{s.get_instance_id()}  {s.get_name()!r}  "
              f"buttons={s.get_numbuttons()} axes={s.get_numaxes()} hats={s.get_numhats()}")
    if not sticks:
        print("[device] no gamepad/HID controllers enumerated by the OS.")
        print("         If the ABXY buttons work inside Rouvy anyway, they pair")
        print("         straight into the app (BLE) and the wrapper cannot read")
        print("         them -- plan on a keyboard hotkey / USB clicker instead.")
    print("\nPress the buttons now. Ctrl+C (or close the window) to stop.\n")

    running = True
    try:
        while running:
            for e in pygame.event.get():
                if e.type == pygame.QUIT:
                    running = False
                elif e.type == pygame.JOYBUTTONDOWN:
                    print(f"  BUTTON DOWN  device#{e.instance_id}  button={e.button}")
                elif e.type == pygame.JOYBUTTONUP:
                    print(f"  button up    device#{e.instance_id}  button={e.button}")
                elif e.type == pygame.JOYHATMOTION:
                    print(f"  HAT/D-PAD    device#{e.instance_id}  value={e.value}")
                elif e.type == pygame.JOYAXISMOTION:
                    if abs(e.value) > 0.5:   # ignore idle jitter
                        print(f"  AXIS        device#{e.instance_id}  axis={e.axis}  {e.value:+.2f}")
                # keyboard, as a cross-check for "buttons mapped to keystrokes":
                elif e.type == pygame.KEYDOWN:
                    print(f"  KEY DOWN     key={pygame.key.name(e.key)!r} (code={e.key})")
            pygame.time.wait(10)
    except KeyboardInterrupt:
        pass
    finally:
        pygame.quit()
        print("\nprobe closed.")


if __name__ == "__main__":
    main()
