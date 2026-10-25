"""Macro byte format (``CMD_MACRO``; one macro per key index, up to 512 bytes).

Body layout::

    u16 repeat count | u16 (length - 4) | entries...

Entry kinds (first byte):

* ``4..236``   keyboard usage (4-231) or mouse button (232 left, 233 right, 234 middle,
               235 back, 236 forward).  ``[val, state|delay]`` when delay <= 127, otherwise
               ``[val, state, 0xFF, d0, d1, d2]`` (state: bit7 set = release).
* ``250``      DPI change: ``[250, lo, hi, delay]`` or ``[250, lo, hi, 0, 0xFF, d0, d1, d2]``
               (long form when delay > 255).
* ``254``      relative pointer move: ``[254, delay, xlo, xhi, ylo, yhi]`` or with a long
               delay ``[254, 0, xlo, xhi, ylo, yhi, 0xFF, d0, d1, d2]``; X/Y are int16.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import keys as K

MOUSE_LEFT, MOUSE_RIGHT, MOUSE_MIDDLE, MOUSE_BACK, MOUSE_FORWARD = 232, 233, 234, 235, 236
KB_START = 4
CPI_KEY = 250
XY_KEY = 254
DELAY_MARK = 255
MAX_BYTES = 512

MOUSE_BUTTON_CODES = {"left": MOUSE_LEFT, "right": MOUSE_RIGHT, "middle": MOUSE_MIDDLE,
                      "back": MOUSE_BACK, "forward": MOUSE_FORWARD}
_MOUSE_NAMES = {v: k for k, v in MOUSE_BUTTON_CODES.items()}


@dataclass
class Step:
    kind: str                 # "key" | "dpi" | "move"
    delay: int = 0            # ms spent *after* this step
    code: int = 0             # key/mouse code ("key")
    release: bool = False     # key released instead of pressed
    dpi: int = 0              # raw 16-bit value written to the device ("dpi")
    dx: int = 0               # "move"
    dy: int = 0

    def describe(self) -> str:
        return _text(self)


@dataclass
class Macro:
    steps: list[Step] = field(default_factory=list)
    repeat: int = 1               # "repeat N times" count (u16)
    repeat_type: int = 0          # 0 times, 1 while held, 2 until next press
    assign_open: bool = False     # high bit of byte 1 in the key slot
    random_delay: int | None = None  # randomised delay (5..100) or None
    fixed_delay: int | None = None   # use this delay (ms) after every step instead of each step's own

    def delay_of(self, step: "Step") -> int:
        return int(self.fixed_delay if self.fixed_delay is not None else step.delay)

    # ---- text form --------------------------------------------------------------
    # one step per line:  down a / up a / click left / delay 30 / dpi 400 / move 10 -5
    @classmethod
    def from_text(cls, text: str, **kw) -> "Macro":
        m = cls(**kw)
        for raw in text.splitlines():
            line = raw.split("#", 1)[0].strip()
            for part in line.split(";"):
                part = part.strip()
                if part:
                    m._add_text_step(part)
        return m

    def _add_text_step(self, line: str) -> None:
        toks = line.lower().split()
        op = toks[0]
        if op == "delay":
            if not self.steps:
                raise ValueError("delay before the first step")
            self.steps[-1].delay += int(toks[1])
            return
        if op in ("down", "up"):
            self.steps.append(Step("key", 0, _code(toks[1]), release=(op == "up")))
        elif op == "press":
            self.steps.append(Step("key", 0, _code(toks[1])))
            self.steps.append(Step("key", 0, _code(toks[1]), release=True))
        elif op == "click":
            code = _code("mouse_" + toks[1] if toks[1] in MOUSE_BUTTON_CODES else toks[1])
            self.steps.append(Step("key", 0, code))
            self.steps.append(Step("key", 0, code, release=True))
        elif op == "dpi":
            self.steps.append(Step("dpi", 0, dpi=int(toks[1])))
        elif op == "move":
            self.steps.append(Step("move", 0, dx=int(toks[1]), dy=int(toks[2])))
        else:
            raise ValueError(f"unknown macro command {line!r}")

    def to_text(self) -> str:
        return "\n".join(_text(s) for s in self.steps)

    # ---- JSON form --------------------------------------------------------------
    def to_dict(self) -> dict:
        return {"repeat": self.repeat, "repeat_type": self.repeat_type,
                "assign_open": self.assign_open, "random_delay": self.random_delay,
                "fixed_delay": self.fixed_delay,
                "steps": [s.__dict__.copy() for s in self.steps]}

    @classmethod
    def from_dict(cls, d: dict) -> "Macro":
        return cls(steps=[Step(**s) for s in d.get("steps", [])], repeat=d.get("repeat", 1),
                   repeat_type=d.get("repeat_type", 0), assign_open=d.get("assign_open", False),
                   random_delay=d.get("random_delay"), fixed_delay=d.get("fixed_delay"))


def _text(s: Step) -> str:
    if s.kind == "key":
        name = _MOUSE_NAMES.get(s.code)
        name = ("mouse_" + name) if name else K.HID_NAMES.get(s.code, str(s.code))
        base = f"{'up' if s.release else 'down'} {name}"
    elif s.kind == "dpi":
        base = f"dpi {s.dpi}"
    else:
        base = f"move {s.dx} {s.dy}"
    return base + (f"; delay {s.delay}" if s.delay else "")


def _code(name: str) -> int:
    name = name.lower()
    if name.startswith("mouse_") and name[6:] in MOUSE_BUTTON_CODES:
        return MOUSE_BUTTON_CODES[name[6:]]
    if name in K.HID_KEYS:
        return K.HID_KEYS[name]
    if name.isdigit():
        return int(name)
    raise ValueError(f"unknown key {name!r}")


# --------------------------------------------------------------------------------------
# encoding
# --------------------------------------------------------------------------------------
def encode(m: Macro) -> bytes:
    """Serialise a macro into the device byte format (without paging)."""
    out = bytearray(4)  # header filled in at the end
    out[0] = m.repeat & 0xFF
    out[1] = (m.repeat >> 8) & 0xFF
    for s in m.steps:
        d = max(0, m.delay_of(s))
        if m.random_delay is not None and d - m.random_delay < 50:
            d = m.random_delay + 50
        if s.kind == "key":
            if not KB_START <= s.code <= MOUSE_FORWARD:
                raise ValueError(f"key code out of range: {s.code}")
            state = 0x80 if s.release else 0
            if d > 127:
                out += bytes((s.code, state, DELAY_MARK)) + _u24(d)
            else:
                out += bytes((s.code, state | d))
        elif s.kind == "dpi":
            out += bytes((CPI_KEY, s.dpi & 0xFF, (s.dpi >> 8) & 0xFF))
            if d > 255:
                out += bytes((0, DELAY_MARK)) + _u24(d)
            else:
                out.append(d)
        elif s.kind == "move":
            x, y = s.dx & 0xFFFF, s.dy & 0xFFFF
            xy = bytes((x & 0xFF, x >> 8, y & 0xFF, y >> 8))
            if d > 255:
                out += bytes((XY_KEY, 0)) + xy + bytes((DELAY_MARK,)) + _u24(d)
            else:
                out += bytes((XY_KEY, d)) + xy
        else:
            raise ValueError(f"unknown step kind {s.kind}")
    if len(out) > MAX_BYTES:
        raise ValueError(f"macro too long: {len(out)} > {MAX_BYTES} bytes")
    if not m.steps:
        out[2] = out[3] = 0
    else:
        n = len(out) - 4
        out[2], out[3] = n & 0xFF, (n >> 8) & 0xFF
    return bytes(out)


def _u24(v: int) -> bytes:
    if v > 0xFFFFFF:
        raise ValueError("delay too large")
    return bytes((v & 0xFF, (v >> 8) & 0xFF, (v >> 16) & 0xFF))


def decode(data: bytes) -> Macro:
    if len(data) < 4:
        return Macro()
    m = Macro(repeat=data[0] | (data[1] << 8))
    total = min((data[2] | (data[3] << 8)) + 4, len(data))
    i = 4
    while i < total:
        v = data[i]
        if KB_START <= v <= MOUSE_FORWARD:
            nxt = data[i + 1] if i + 1 < total else 0
            release = bool(nxt >> 7)
            if i + 2 < total and data[i + 2] == DELAY_MARK and i + 5 < len(data):
                delay = (nxt & 0x7F) + data[i + 3] + (data[i + 4] << 8) + (data[i + 5] << 16)
                size = 6
            else:
                delay = nxt & 0x7F
                size = 2
            m.steps.append(Step("key", delay, v, release=release))
            i += size
        elif v == CPI_KEY:
            val = data[i + 1] | (data[i + 2] << 8)
            if i + 4 < total and data[i + 4] == DELAY_MARK and i + 7 < len(data):
                delay = data[i + 3] + data[i + 5] + (data[i + 6] << 8) + (data[i + 7] << 16)
                size = 8
            else:
                delay = data[i + 3] if i + 3 < len(data) else 0
                size = 4
            m.steps.append(Step("dpi", delay, dpi=val))
            i += size
        elif v == XY_KEY:
            delay = data[i + 1]
            x = _s16(data[i + 2] | (data[i + 3] << 8))
            y = _s16(data[i + 4] | (data[i + 5] << 8))
            size = 6
            if i + 6 < total and data[i + 6] == DELAY_MARK and i + 9 < len(data):
                delay = data[i + 7] + (data[i + 8] << 8) + (data[i + 9] << 16)
                size = 10
            m.steps.append(Step("move", delay, dx=x, dy=y))
            i += size
        else:
            i += 2  # unknown byte pair: skipped by the vendor app as well
    return m


def _s16(v: int) -> int:
    return v - 0x10000 if v & 0x8000 else v


def steps_from_events(events: list[tuple[float, int, bool]], min_delay: int = 1) -> list[Step]:
    """Turn recorded key events ``(time_ms, hid_code, is_release)`` into macro steps.

    The delay of a step is the time until the next event, so replaying keeps the original rhythm.
    """
    steps: list[Step] = []
    for i, (t, code, release) in enumerate(events):
        gap = events[i + 1][0] - t if i + 1 < len(events) else 0
        steps.append(Step("key", max(min_delay, int(round(gap))) if i + 1 < len(events) else 0, code,
                          release=release))
    return steps


def common_delay(macro: Macro) -> int | None:
    """The shared delay when every step has the same one (the vendor app shows that as 'fixed delay')."""
    delays = {s.delay for s in macro.steps}
    return delays.pop() if len(macro.steps) > 1 and len(delays) == 1 else None


def pages(data: bytes) -> list[tuple[int, bytes]]:
    """Split a macro into the (address, chunk) writes the vendor app performs."""
    out = []
    for addr in range(0, len(data), K_PAGE):
        out.append((addr, data[addr:addr + K_PAGE]))
    return out


K_PAGE = 32


# --------------------------------------------------------------------------------------
# presets shipped with the vendor app
# --------------------------------------------------------------------------------------
def _clicks(n: int, delay: int) -> list[Step]:
    steps = []
    for _ in range(n):
        steps.append(Step("key", delay, MOUSE_LEFT))
        steps.append(Step("key", delay, MOUSE_LEFT, release=True))
    return steps


def preset(name: str, *, fire_interval: int = 50) -> tuple[Macro, int]:
    """Return ``(macro, repeat_type)`` for the macro-backed button actions."""
    if name == "double_click":
        return Macro(_clicks(2, 60), repeat=1, repeat_type=0), 0
    if name == "triple_click":
        return Macro(_clicks(3, 60), repeat=1, repeat_type=0), 0
    if name == "fire":
        return Macro(_clicks(1, fire_interval), repeat=1, repeat_type=1), 1
    if name == "aim":
        return Macro([Step("dpi", 200, dpi=400)], repeat=1, repeat_type=1), 1
    raise ValueError(name)
