"""
test_input_trigger.py

Unit tests for the button->action mapping (input_trigger.map_event). This is
the part that matters and the part that must not need hardware: the pygame
plumbing is a thin drain-the-queue loop around this pure function.
"""

from input_trigger import (LEAVE_MESSAGE, OPTION_1, OPTION_2, QUIT, map_event)

BUTTONS = {0: LEAVE_MESSAGE, 1: OPTION_1, 2: OPTION_2}
KEYS = {32: LEAVE_MESSAGE, 49: OPTION_1, 113: QUIT}   # space, '1', 'q' codes


def test_gamepad_button_maps_to_action():
    assert map_event("button", 0, BUTTONS, KEYS) == LEAVE_MESSAGE
    assert map_event("button", 2, BUTTONS, KEYS) == OPTION_2


def test_keyboard_key_maps_to_action():
    assert map_event("key", 32, BUTTONS, KEYS) == LEAVE_MESSAGE
    assert map_event("key", 113, BUTTONS, KEYS) == QUIT


def test_unmapped_control_is_ignored():
    assert map_event("button", 9, BUTTONS, KEYS) is None
    assert map_event("key", 999, BUTTONS, KEYS) is None


def test_unknown_kind_is_ignored():
    assert map_event("wheel", 0, BUTTONS, KEYS) is None


def test_button_and_key_spaces_are_independent():
    # same code number means different things on button vs key -> no crosstalk
    assert map_event("button", 1, BUTTONS, KEYS) == OPTION_1
    assert map_event("key", 1, BUTTONS, KEYS) is None
