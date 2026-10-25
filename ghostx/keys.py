"""Button / wheel function encoding.

Each physical key has a 4-byte function slot (``CMD_KEY_MATRIX`` address ``index * 4``; the
scroll wheel uses ``CMD_WHEEL``).  The first byte is the function class, the rest depend on it.
Functions that need a macro (double click, fire, ...) additionally store a macro under the same
key index, see :mod:`ghostx.macros`.
"""

from __future__ import annotations

from dataclasses import dataclass

# Function classes (first byte of the slot)
F_NONE = 0
F_MOUSE = 1
F_KEYBOARD = 2
F_ACPI = 3
F_MEDIA = 4
F_SCROLL = 5
F_RATE = 6
F_DPI = 8
F_PROFILE = 9
F_MACRO = 10
F_ACSCROLL = 11

MOUSE_BITS = {"left": 1, "right": 2, "middle": 4, "back": 8, "forward": 16}

# HID keyboard usage ids (usage page 7)
_HID_NAMED = {
    "enter": 40, "esc": 41, "escape": 41, "backspace": 42, "tab": 43, "space": 44, "minus": 45,
    "equal": 46, "lbracket": 47, "rbracket": 48, "backslash": 49, "semicolon": 51, "quote": 52,
    "grave": 53, "comma": 54, "dot": 55, "slash": 56, "capslock": 57, "printscreen": 70,
    "scrolllock": 71, "pause": 72, "insert": 73, "home": 74, "pageup": 75, "delete": 76,
    "end": 77, "pagedown": 78, "right": 79, "left": 80, "down": 81, "up": 82, "numlock": 83,
    "menu": 101, "lctrl": 224, "ctrl": 224, "lshift": 225, "shift": 225, "lalt": 226, "alt": 226,
    "lgui": 227, "win": 227, "gui": 227, "rctrl": 228, "rshift": 229, "ralt": 230, "rgui": 231,
}
HID_KEYS: dict[str, int] = dict(_HID_NAMED)
for _i, _c in enumerate("abcdefghijklmnopqrstuvwxyz"):
    HID_KEYS[_c] = 4 + _i
for _i, _c in enumerate("1234567890"):
    HID_KEYS[_c] = 30 + _i
for _i in range(1, 13):
    HID_KEYS[f"f{_i}"] = 57 + _i
for _i in range(13, 25):
    HID_KEYS[f"f{_i}"] = 104 + (_i - 13)
HID_NAMES: dict[int, str] = {}
for _n, _v in HID_KEYS.items():
    HID_NAMES.setdefault(_v, _n)
HID_NAMES.update({224: "lctrl", 225: "lshift", 226: "lalt", 227: "lgui", 228: "rctrl",
                  229: "rshift", 230: "ralt", 231: "rgui", 41: "esc"})
MODIFIERS = {224, 225, 226, 227, 228, 229, 230, 231}

# Consumer-control usages used by the media class
_MEDIA = {
    "browser": 547, "player": 387, "mail": 394, "volume_up": 233, "volume_down": 234,
    "previous": 182, "next": 181, "mute": 226, "play_pause": 205, "stop": 183,
    "calculator": 402, "brightness_up": 111, "brightness_down": 112,
}

# Simple (single class + argument) functions
_SIMPLE: dict[str, tuple[int, ...]] = {
    "none": (F_NONE, 0, 0, 0),
    "left_click": (F_MOUSE, MOUSE_BITS["left"]),
    "middle_click": (F_MOUSE, MOUSE_BITS["middle"]),
    "right_click": (F_MOUSE, MOUSE_BITS["right"]),
    "back": (F_MOUSE, MOUSE_BITS["back"]),
    "forward": (F_MOUSE, MOUSE_BITS["forward"]),
    "dpi_cycle": (F_DPI, 3),
    "dpi_up": (F_DPI, 1),
    "dpi_down": (F_DPI, 2),
    "rate_cycle": (F_RATE, 3),
    "profile_cycle": (F_PROFILE, 3),
    "profile_up": (F_PROFILE, 1),
    "profile_down": (F_PROFILE, 2),
    "profile_1": (F_PROFILE, 4, 0),
    "profile_2": (F_PROFILE, 4, 1),
    "profile_3": (F_PROFILE, 4, 2),
    "power_off": (F_ACPI, 1),
    "sleep": (F_ACPI, 2),
    "wake": (F_ACPI, 3),
    "scroll_left": (F_ACSCROLL, 1),
    "scroll_right": (F_ACSCROLL, 129),
    "scroll_up": (F_SCROLL, 1),
    "scroll_down": (F_SCROLL, 129),
    # keyboard shortcuts shipped with the vendor app
    "page_up": (F_KEYBOARD, 75),
    "page_down": (F_KEYBOARD, 78),
    "copy": (F_KEYBOARD, 224, 6),
    "paste": (F_KEYBOARD, 224, 25),
    "undo": (F_KEYBOARD, 224, 29),
    "select_all": (F_KEYBOARD, 224, 4),
    "search": (F_KEYBOARD, 224, 9),
    "close_window": (F_KEYBOARD, 226, 61),
    "show_desktop": (F_KEYBOARD, 227, 7),
    "my_computer": (F_KEYBOARD, 227, 8),
    "lock_pc": (F_KEYBOARD, 227, 15),
}
for _n, _u in _MEDIA.items():
    _SIMPLE[_n] = (F_MEDIA, _u & 0xFF, _u >> 8)

# Functions realised with a macro stored next to the key
MACRO_ACTIONS = ("double_click", "triple_click", "fire", "aim")

ACTIONS = tuple(_SIMPLE) + MACRO_ACTIONS


def _pad(b: tuple[int, ...] | list[int]) -> bytes:
    b = bytes(b)[:4]
    return b + bytes(4 - len(b))


_REVERSE = {}
for _n, _b in _SIMPLE.items():
    _REVERSE.setdefault(_pad(_b), _n)


@dataclass
class KeyFunction:
    """A decoded slot.  ``name`` is an action name, ``key:<combo>``, ``macro`` or ``raw:<hex>``."""

    name: str
    raw: bytes

    def __str__(self) -> str:
        return self.name


def parse_key_spec(spec: str) -> bytes:
    """``key:ctrl+shift+a`` -> keyboard slot bytes (at most three HID usages)."""
    combo = spec.split(":", 1)[1] if ":" in spec else spec
    codes = []
    for part in combo.lower().replace(" ", "").split("+"):
        if not part:
            raise ValueError(f"bad key combination {spec!r}")
        if part.isdigit() and part not in HID_KEYS:
            codes.append(int(part))
        elif part in HID_KEYS:
            codes.append(HID_KEYS[part])
        else:
            raise ValueError(f"unknown key {part!r} in {spec!r}")
    if not 1 <= len(codes) <= 3:
        raise ValueError("a keyboard function takes between one and three keys")
    return _pad((F_KEYBOARD, *codes))


def encode(spec: str) -> bytes | None:
    """Encode an action spec into the 4-byte slot.

    Returns ``None`` for macro-backed actions (``double_click`` ...) and ``macro`` -- those
    are handled by the device layer because they also need the macro body.
    """
    spec = spec.strip()
    low = spec.lower()
    if low in MACRO_ACTIONS or low == "macro" or low.startswith("macro:"):
        return None
    if low in _SIMPLE:
        return _pad(_SIMPLE[low])
    if low.startswith("key:"):
        return parse_key_spec(low)
    if low.startswith("raw:"):
        data = bytes.fromhex(low[4:].replace("-", "").replace(" ", ""))
        if len(data) != 4:
            raise ValueError("raw slot must be 4 bytes")
        return data
    raise ValueError(f"unknown button function {spec!r}")


def decode(slot: bytes) -> KeyFunction:
    slot = bytes(slot)[:4].ljust(4, b"\0")
    if slot in _REVERSE:
        return KeyFunction(_REVERSE[slot], slot)
    cls = slot[0]
    if cls == F_NONE:
        return KeyFunction("none", slot)
    if cls == F_KEYBOARD:
        codes = [c for c in slot[1:] if c]
        if codes:
            return KeyFunction("key:" + "+".join(HID_NAMES.get(c, str(c)) for c in codes), slot)
    if cls == F_MACRO:
        return KeyFunction("macro", slot)
    return KeyFunction("raw:" + slot.hex("-"), slot)


def macro_slot(repeat_type: int, key_index: int, *, assign: bool = False,
               random_delay: int | None = None) -> bytes:
    """Slot bytes for macro-backed functions.

    ``repeat_type``: 0 = repeat N times, 1 = repeat while held, 2 = until pressed again.
    """
    b3 = 0
    if random_delay is not None:
        b3 = 0x80 | (random_delay & 0x7F)
    return bytes((F_MACRO, ((0x80 if assign else 0) | (repeat_type & 0x7F)), key_index & 0xFF, b3))


def macro_slot_fields(slot: bytes) -> dict:
    return {
        "assign": bool(slot[1] & 0x80),
        "repeat_type": slot[1] & 0x7F,
        "key_index": slot[2],
        "random": bool(slot[3] & 0x80),
        "random_delay": slot[3] & 0x7F,
    }


# Human readable description of every button function, grouped for `ghostx help functions`
ACTION_HELP: dict[str, list[tuple[str, str]]] = {
    "Mouse buttons": [
        ("left_click", "Left mouse button"), ("middle_click", "Middle mouse button (wheel click)"),
        ("right_click", "Right mouse button"), ("back", "Browser back (mouse button 4)"),
        ("forward", "Browser forward (mouse button 5)"), ("none", "Disable the button"),
        ("double_click", "Two quick left clicks per press (macro)"),
        ("triple_click", "Three quick left clicks per press (macro)"),
        ("fire", "Repeated left clicks while held; speed set with --fire-interval ms (macro)"),
        ("aim", "Lower DPI to 400 while held, restore on release (macro)"),
    ],
    "DPI": [
        ("dpi_cycle", "Switch to the next enabled DPI stage"), ("dpi_up", "Next higher DPI stage"),
        ("dpi_down", "Next lower DPI stage"),
    ],
    "Polling rate / profile": [
        ("rate_cycle", "Cycle the polling rate"), ("profile_cycle", "Next profile (1-3)"),
        ("profile_up", "Next profile"), ("profile_down", "Previous profile"),
        ("profile_1", "Jump to profile 1"), ("profile_2", "Jump to profile 2"),
        ("profile_3", "Jump to profile 3"),
    ],
    "Scrolling": [
        ("scroll_up", "Scroll up"), ("scroll_down", "Scroll down"),
        ("scroll_left", "Scroll left (horizontal)"), ("scroll_right", "Scroll right (horizontal)"),
        ("page_up", "Page Up key"), ("page_down", "Page Down key"),
    ],
    "Media": [
        ("volume_up", "Volume up"), ("volume_down", "Volume down"), ("mute", "Mute"),
        ("play_pause", "Play / pause"), ("stop", "Stop"), ("previous", "Previous track"),
        ("next", "Next track"), ("player", "Open media player"), ("browser", "Open web browser"),
        ("mail", "Open mail client"), ("calculator", "Open calculator"),
        ("brightness_up", "Screen brightness up"), ("brightness_down", "Screen brightness down"),
    ],
    "Windows shortcuts": [
        ("copy", "Ctrl+C"), ("paste", "Ctrl+V"), ("undo", "Ctrl+Z"), ("select_all", "Ctrl+A"),
        ("search", "Ctrl+F"), ("close_window", "Alt+F4"), ("show_desktop", "Win+D"),
        ("my_computer", "Win+E"), ("lock_pc", "Win+L"),
    ],
    "Power": [
        ("power_off", "ACPI power button"), ("sleep", "ACPI sleep"), ("wake", "ACPI wake"),
    ],
    "Custom": [
        ("key:<combo>", "Any keyboard shortcut of 1-3 keys, e.g. key:ctrl+shift+a, key:f5, key:win+d"),
        ("macro", "A recorded sequence; define with `ghostx macro <button> <file>` or the GUI"),
        ("raw:xx-xx-xx-xx", "Write the 4-byte slot directly (advanced; shown when a slot is unknown)"),
    ],
}

# Names for the Ghost X hardware
BUTTONS = ("left", "middle", "right", "back", "forward", "dpi")
WHEEL = ("up", "down")
DEFAULT_BUTTON_FUNCTIONS = ("left_click", "middle_click", "right_click", "back", "forward", "dpi_cycle")
DEFAULT_WHEEL_FUNCTIONS = ("scroll_up", "scroll_down")
