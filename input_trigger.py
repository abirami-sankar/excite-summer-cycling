"""
input_trigger.py -- one abstract "the rider pressed something" event source.

The record-a-message feature needs a button the rider can press WHILE pedalling,
without touching the laptop keyboard/mouse (those are busy driving VS Code / the
capture tools). The clean answer is a handheld GAMEPAD. But we don't yet know
whether the rigged bike's own ABXY buttons are even visible to this PC (see
probe_input.py) -- so the trigger SOURCE has to be swappable without touching
the record-and-drop logic that sits on top.

This module is that seam. `InputTrigger.poll()` returns a list of high-level
ACTION names ("leave_message", "option_1", ...) each time a mapped control goes
down -- and it listens to a gamepad AND the keyboard at the same time, so the
exact same object works on the rig (gamepad) and at a desk (keyboard fallback).
Because it's built on `pygame.joystick` -- the same API probe_input.py uses --
if the bike's ABXY buttons turn out to be an OS gamepad, wiring them is just a
button-number change in the map, no new code.

The button->action MAPPING is a pure function (`map_event`) so it's unit-tested
without any hardware; the pygame plumbing around it is the only part that needs
a device.
"""

import os

# Deliver gamepad events even when our window is in the BACKGROUND: on the rig
# Rouvy is the focused app while the rider presses the pad, and SDL otherwise
# drops joystick events for a background app. Must be set before SDL initialises.
os.environ.setdefault("SDL_JOYSTICK_ALLOW_BACKGROUND_EVENTS", "1")

# high-level actions the rest of the app reacts to (never raw button numbers)
LEAVE_MESSAGE = "leave_message"
OPTION_1 = "option_1"
OPTION_2 = "option_2"
OPTION_3 = "option_3"
QUIT = "quit"

# Defaults are a guess for a generic USB gamepad; confirm the real numbers with
# probe_input.py and pass your own maps. Keyboard doubles as the desk fallback.
DEFAULT_BUTTON_MAP = {0: LEAVE_MESSAGE, 1: OPTION_1, 2: OPTION_2, 3: OPTION_3}
DEFAULT_KEY_MAP = {  # pygame key codes filled in lazily (see _default_key_map)
}


def map_event(kind, code, button_map, key_map):
    """Pure: turn a (kind, code) control-down into an action name, or None.

    ``kind`` is "button" (gamepad) or "key" (keyboard); ``code`` is the button
    index or the pygame key code. Unknown controls map to None so unrelated
    presses are simply ignored. No pygame needed -- this is the tested core.
    """
    if kind == "button":
        return button_map.get(code)
    if kind == "key":
        return key_map.get(code)
    return None


def _default_key_map():
    import pygame
    return {
        pygame.K_SPACE: LEAVE_MESSAGE,
        pygame.K_1: OPTION_1,
        pygame.K_2: OPTION_2,
        pygame.K_3: OPTION_3,
        pygame.K_q: QUIT,
        pygame.K_ESCAPE: QUIT,
    }


class InputTrigger:
    """Edge-triggered action source over a gamepad + keyboard (pygame).

    SDL only delivers input events while its event loop runs, which needs the
    video subsystem and a focused window -- so a small window is opened (same
    reason as probe_input.py). Keep it focused while pressing.
    """

    def __init__(self, *, button_map=None, key_map=None, window_title="ride input"):
        import pygame
        self._pygame = pygame
        self.button_map = dict(DEFAULT_BUTTON_MAP if button_map is None else button_map)
        pygame.init()
        pygame.joystick.init()
        self.key_map = dict(_default_key_map() if key_map is None else key_map)
        self._screen = pygame.display.set_mode((360, 90))
        pygame.display.set_caption(window_title)
        self.pads = [pygame.joystick.Joystick(i) for i in range(pygame.joystick.get_count())]
        for p in self.pads:
            p.init()

    @property
    def gamepad_names(self):
        return [p.get_name() for p in self.pads]

    def poll(self):
        """Drain pending events; return the actions whose controls went DOWN."""
        pygame = self._pygame
        actions = []
        for e in pygame.event.get():
            if e.type == pygame.QUIT:
                actions.append(QUIT)
            elif e.type == pygame.JOYBUTTONDOWN:
                a = map_event("button", e.button, self.button_map, self.key_map)
                if a:
                    actions.append(a)
            elif e.type == pygame.KEYDOWN:
                a = map_event("key", e.key, self.button_map, self.key_map)
                if a:
                    actions.append(a)
        return actions

    def close(self):
        try:
            self._pygame.display.quit()
        except Exception:
            pass
