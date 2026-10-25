"""Human friendly names and key-capture helpers for the GUI."""

from __future__ import annotations

from .. import keys as K

_NAMES = {
    "none": "Disabled", "left_click": "Left click", "middle_click": "Middle click",
    "right_click": "Right click", "back": "Back", "forward": "Forward",
    "double_click": "Double click", "triple_click": "Triple click", "fire": "Fire key",
    "aim": "Sniper (aim)", "dpi_cycle": "DPI cycle", "dpi_up": "DPI +", "dpi_down": "DPI −",
    "rate_cycle": "Polling rate cycle", "profile_cycle": "Next profile", "profile_up": "Profile +",
    "profile_down": "Profile −", "profile_1": "Profile 1", "profile_2": "Profile 2",
    "profile_3": "Profile 3", "led_speed": "Light speed", "scroll_up": "Scroll up",
    "scroll_down": "Scroll down", "scroll_left": "Scroll left", "scroll_right": "Scroll right",
    "page_up": "Page Up", "page_down": "Page Down", "volume_up": "Volume +", "volume_down": "Volume −",
    "mute": "Mute", "play_pause": "Play / Pause", "stop": "Stop", "previous": "Previous track",
    "next": "Next track", "player": "Media player", "browser": "Browser", "mail": "Mail",
    "calculator": "Calculator", "brightness_up": "Screen brightness +", "brightness_down": "Screen brightness −",
    "copy": "Copy", "paste": "Paste", "undo": "Undo", "select_all": "Select all", "search": "Find",
    "close_window": "Close window", "show_desktop": "Show desktop", "my_computer": "File Explorer",
    "lock_pc": "Lock PC", "power_off": "Power off", "sleep": "Sleep", "wake": "Wake up",
    "macro": "Macro",
}

_KEYNAMES = {"ctrl": "Ctrl", "lctrl": "Ctrl", "rctrl": "R-Ctrl", "shift": "Shift", "lshift": "Shift",
             "rshift": "R-Shift", "alt": "Alt", "lalt": "Alt", "ralt": "R-Alt", "win": "Win", "lgui": "Win",
             "rgui": "R-Win", "gui": "Win", "esc": "Esc", "enter": "Enter", "pageup": "PgUp",
             "pagedown": "PgDn", "printscreen": "PrtSc", "capslock": "Caps"}

CATEGORY_TITLES = {
    "Mouse buttons": "Mouse", "DPI": "DPI", "Polling rate / profile": "Profile",
    "Scrolling": "Scrolling", "Media": "Media", "Windows shortcuts": "Shortcuts", "Power": "Power",
    "Custom": "Custom",
}


def friendly(fn: str) -> str:
    fn = (fn or "").strip()
    if fn in _NAMES:
        return _NAMES[fn]
    if fn.startswith("key:"):
        parts = fn[4:].split("+")
        return " + ".join(_KEYNAMES.get(p, p.upper() if len(p) <= 2 else p.title()) for p in parts)
    if fn.startswith("raw:"):
        return "Custom (raw)"
    return fn.replace("_", " ").title()


# --------------------------------------------------------------------- key capture (Tk keysym -> ghostx key name)
KEYSYM = {
    "Return": "enter", "Escape": "esc", "space": "space", "BackSpace": "backspace", "Tab": "tab",
    "Left": "left", "Right": "right", "Up": "up", "Down": "down", "Prior": "pageup", "Next": "pagedown",
    "Home": "home", "End": "end", "Insert": "insert", "Delete": "delete", "Caps_Lock": "capslock",
    "minus": "minus", "equal": "equal", "bracketleft": "lbracket", "bracketright": "rbracket",
    "backslash": "backslash", "semicolon": "semicolon", "apostrophe": "quote", "grave": "grave",
    "comma": "comma", "period": "dot", "slash": "slash", "Print": "printscreen",
    "Scroll_Lock": "scrolllock", "Pause": "pause", "Num_Lock": "numlock", "Menu": "menu",
}
MODIFIER_KEYSYMS = {"Control_L", "Control_R", "Shift_L", "Shift_R", "Alt_L", "Alt_R", "Super_L", "Super_R",
                    "Meta_L", "Meta_R"}


def keysym_to_name(keysym: str) -> str | None:
    if keysym in KEYSYM:
        return KEYSYM[keysym]
    k = keysym.lower()
    if k in K.HID_KEYS and len(k) <= 3:
        return k
    return None


_MODIFIER_HID = {"Control_L": 224, "Shift_L": 225, "Alt_L": 226, "Super_L": 227, "Win_L": 227,
                 "Control_R": 228, "Shift_R": 229, "Alt_R": 230, "Super_R": 231, "Win_R": 231}


def keysym_to_hid(keysym: str) -> int | None:
    """Tk keysym -> HID keyboard usage id (modifiers included); None if the key can't be used."""
    if keysym in _MODIFIER_HID:
        return _MODIFIER_HID[keysym]
    name = keysym_to_name(keysym)
    return K.HID_KEYS.get(name) if name else None
