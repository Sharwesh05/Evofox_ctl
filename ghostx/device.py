"""High level API for the EvoFox Ghost X."""

from __future__ import annotations

import contextlib
import random
import threading
import time
from dataclasses import dataclass, field
from typing import Callable

from . import dpi as D
from . import keys as K
from . import macros as M
from . import protocol as P
from .transport import Transport

REPORT_RATES_HZ = (125, 250, 500, 1000, 2000, 4000, 8000)
# Ghost X is an "M400" series device: UI index (1..7) <-> hardware code
_RATE_HW = {1: 64, 2: 32, 3: 16, 4: 8, 5: 4, 6: 2, 7: 1}
_RATE_FROM_HW = {v: k for k, v in _RATE_HW.items()}
SCENE_MODES = ("fire_all_out", "long_endurance", "endurance")
_SCENE_HW = (1, 17, 33)
# sensors for which the LOD (lift-off distance) option exists, with their hardware codes
_LOD_HW = {6: (0, 2), 14: (0, 2), 12: (0, 2), 13: (0, 2), 7: (2, 3)}

DPI_STAGES = P.MAX_DPI_GEAR


@dataclass(frozen=True)
class Capabilities:
    """Sensor options the vendor app enables per chip id (see SetFuncByChip)."""
    ripple: bool = False
    jitter: bool = False
    line_correction: bool = False
    lod: bool = False
    lod_labels: tuple[str, str] = ("Low", "High")
    track_optimization: bool = False
    motion_sync: bool = False


def capabilities(chip: int) -> Capabilities:
    if chip in (0, 1, 2, 11):
        return Capabilities()
    if chip == 3:
        return Capabilities(line_correction=True)
    if chip in (4,):
        return Capabilities(ripple=True, line_correction=True, lod=True, lod_labels=("1 mm", "2 mm"))
    if chip in (6, 14):
        return Capabilities(ripple=True, line_correction=True, lod=True, lod_labels=("1 mm", "2 mm"),
                            motion_sync=True)
    if chip == 7:
        return Capabilities(ripple=True, line_correction=True, lod=True, lod_labels=("2 mm", "3 mm"))
    if chip == 8:
        return Capabilities(ripple=True, line_correction=True)
    if chip in (9, 10):
        return Capabilities(track_optimization=True)
    if chip in (12, 13):
        return Capabilities(jitter=True, lod=True, lod_labels=("1 mm", "2 mm"))
    return Capabilities(ripple=True, line_correction=True)  # unknown sensor: be permissive


class DeviceError(P.ProtocolError):
    pass


@dataclass
class Status:
    connected: bool          # mouse linked to the dongle (always True when wired)
    battery: int             # percent
    charging: bool
    chip: int
    chip_name: str = ""

    def __post_init__(self):
        self.chip_name = D.CHIP_NAMES.get(self.chip, f"#{self.chip}")


@dataclass
class DpiState:
    enabled: list[bool]
    current: int                  # 1-based stage
    values: list[int | None]      # real DPI per stage
    colors: list[str] = field(default_factory=list)   # indicator colour per stage, '#RRGGBB'


@dataclass
class Settings:
    sleep_seconds: int = 60
    debounce_ms: int = 8
    move_to_wake: bool = False
    track_optimization: bool = False
    motion_sync: bool = False
    ripple_or_jitter: bool = False
    line_correction: bool = False
    lod: int = 0                  # 0 low / 1 high (chip specific mm values)
    scene_mode: int = 1           # index into SCENE_MODES


class GhostX:
    """Protocol client.  Thread-safe: every public operation holds a lock."""

    def __init__(self, transport: Transport, *, dry_run: bool = False,
                 log: Callable[[str], None] | None = None, sleep: Callable[[float], None] = time.sleep):
        self.t = transport
        self.dry_run = dry_run
        self._log = log or (lambda s: None)
        self._sleep = sleep
        self._lock = threading.RLock()
        self._seq = 0
        self._chip: int | None = None
        self.last_status: Status | None = None
        self._profile: int | None = None
        self._batch = 0

    # ------------------------------------------------------------------ plumbing
    def close(self) -> None:
        self.t.close()

    def __enter__(self) -> "GhostX":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def _delay(self, ms: int) -> None:
        if ms:
            self._sleep(ms / 1000.0)

    def _next_seq(self) -> int:
        self._seq = (self._seq + 1) & 0xFF
        return self._seq

    def _send(self, cmd: int, did: int, addr: int, length: int, payload: bytes = b"") -> None:
        self._delay(P.DELAY_BEFORE_SET)
        payload = bytes(payload).ljust(length, b"\0")[:length] if payload else b""
        frame = P.build_frame(self.t.feature_len, cmd, self._next_seq(), did, addr, length, payload)
        is_write = not (cmd & P.READ_FLAG)
        if self.dry_run and is_write:
            self._log(f"[dry-run] cmd={cmd} did={did} addr={addr} len={length} data={payload.hex(' ')}")
            return
        self._log(f"{'W' if is_write else 'R?'} cmd={cmd & 0x7f} did={did} addr={addr} len={length} "
                  f"data={payload.hex(' ')}")
        self.t.send_feature(frame)
        self._delay(P.DELAY_AFTER_SET)

    def read(self, cmd: int, did: int, addr: int, length: int) -> bytes:
        """Read ``length`` bytes (retrying like the vendor app does)."""
        with self._lock:
            hw_cmd = cmd | P.READ_FLAG
            for _ in range(P.READ_RETRIES):
                self._send(hw_cmd, did, addr, length)
                self._delay(P.DELAY_BEFORE_GET)
                reply = self.t.get_feature()
                data = P.parse_reply(reply, hw_cmd, did, length)
                if data is not None:
                    self._log(f"R  cmd={cmd} did={did} addr={addr} -> {data.hex(' ')}")
                    return data
            raise DeviceError(f"no valid reply for read cmd={cmd} did={did} addr={addr} len={length}"
                              " (is the mouse awake / connected to the dongle?)")

    def write(self, cmd: int, did: int, addr: int, payload: bytes) -> None:
        with self._lock:
            self._send(cmd, did, addr, len(payload), payload)

    @contextlib.contextmanager
    def batch(self):
        """Group writes; the profile random-id is refreshed once at the end."""
        with self._lock:
            self._batch += 1
            try:
                yield self
            finally:
                self._batch -= 1
            if self._batch == 0:
                self.touch()

    def touch(self) -> None:
        """Change the profile's random id so the vendor web app re-reads the device."""
        if self._batch:
            return
        prof = self.get_profile()
        value = random.randint(1, 0xFFFE)
        self.write(P.CMD_PROFILE, P.DID_RANDOM_ID, prof * 2, bytes((value >> 8, value & 0xFF)))

    # ------------------------------------------------------------------ status
    def status(self) -> Status:
        d = self.read(P.CMD_CONN_BATTERY, 0, 0, 3)
        self._chip = d[2]
        self.last_status = Status(connected=d[0] != 0, battery=min(d[1] & 0x7F, 100),
                                  charging=bool(d[1] >> 7), chip=d[2])
        return self.last_status

    @property
    def chip(self) -> int:
        if self._chip is None:
            self.status()
        return self._chip or 0

    # ------------------------------------------------------------------ profiles
    def get_profile(self) -> int:
        self._profile = self.read(P.CMD_PROFILE, P.DID_PROFILE, 0, 1)[0]
        return self._profile

    def set_profile(self, index: int) -> None:
        if not 0 <= index < P.PROFILE_COUNT:
            raise ValueError(f"profile must be 0..{P.PROFILE_COUNT - 1}")
        self.write(P.CMD_PROFILE, P.DID_PROFILE, 0, bytes((index,)))
        self._profile = index

    # ------------------------------------------------------------------ DPI
    def get_dpi(self) -> DpiState:
        d = self.read(P.CMD_DPI_VALUE, 0, 0, 20)
        mask, current = d[0], d[1]
        multi = d[18] | (d[19] << 8)
        chip = self.chip
        values = []
        for i in range(DPI_STAGES):
            hw = d[2 + 2 * i] | (d[3 + 2 * i] << 8)
            values.append(D.from_hardware(chip, hw, (multi >> (2 * i)) & 3))
        c = self.read(P.CMD_DPI_COLOR, 0, 0, 24)
        colors = []
        for i in range(DPI_STAGES):
            g, r, b = c[3 * i], c[3 * i + 1], c[3 * i + 2]            # the mouse stores G, R, B
            colors.append(f"#{r:02X}{g:02X}{b:02X}")
        return DpiState([bool(mask >> i & 1) for i in range(DPI_STAGES)], current, values, colors)

    def set_dpi(self, values: list[int] | None = None, enabled: list[bool] | None = None,
                current: int | None = None, colors: list[str] | None = None) -> None:
        """Write the DPI stage table.  Omitted arguments keep their current device value."""
        state = self.get_dpi()
        chip = self.chip
        vals = list(values) if values is not None else [
            v if v is not None else D.table(chip)[0].dpi for v in state.values]
        en = list(enabled) if enabled is not None else state.enabled
        cur = current if current is not None else state.current
        if len(vals) != DPI_STAGES or len(en) != DPI_STAGES:
            raise ValueError(f"{DPI_STAGES} DPI stages are required")
        if not 1 <= cur <= DPI_STAGES:
            raise ValueError("current DPI stage must be 1..8")
        if not any(en):
            raise ValueError("at least one DPI stage must be enabled")
        if not en[cur - 1]:
            raise ValueError("current DPI stage must be enabled")
        mask, multi, body = 0, 0, bytearray()
        for i, (v, e) in enumerate(zip(vals, en)):
            entry = D.lookup(chip, int(v))
            mask |= (1 if e else 0) << i
            multi |= (entry.ratio or 0) << (2 * i)
            body += P.le16(entry.hw)
        payload = bytes((mask, cur)) + bytes(body) + P.le16(multi)
        with self.batch():
            self.write(P.CMD_DPI_VALUE, 0, 0, payload)
            if colors is not None:
                self.set_dpi_colors(colors)

    def set_dpi_colors(self, colors: list[str]) -> None:
        """Set the indicator colour of each of the 8 DPI stages."""
        if len(colors) != DPI_STAGES:
            raise ValueError("8 colours are required")
        body = bytearray()
        for c in colors:
            c = D.parse_color(c)
            r, g, b = int(c[1:3], 16), int(c[3:5], 16), int(c[5:7], 16)
            body += bytes((g, r, b))                                 # device order is G, R, B
        with self.batch():
            self.write(P.CMD_DPI_COLOR, 0, 0, bytes(body))

    # ------------------------------------------------------------------ report rate
    def get_report_rate(self) -> int:
        code = self.read(P.CMD_REPORT_RATE, 0, 0, 1)[0]
        idx = _RATE_FROM_HW.get(code)
        if idx is None:
            raise DeviceError(f"unknown report-rate code {code}")
        return REPORT_RATES_HZ[idx - 1]

    def set_report_rate(self, hz: int) -> None:
        if hz not in REPORT_RATES_HZ:
            raise ValueError(f"report rate must be one of {REPORT_RATES_HZ}")
        with self.batch():
            self.write(P.CMD_REPORT_RATE, 0, 0, bytes((_RATE_HW[REPORT_RATES_HZ.index(hz) + 1],)))

    # ------------------------------------------------------------------ settings
    def get_settings(self) -> Settings:
        s = Settings()
        s.sleep_seconds = P.u16(*self.read(P.CMD_PROFILE, P.DID_SLEEP_TIME, 0, 2))
        s.debounce_ms = self.read(P.CMD_PARAMETER, P.DID_SHORT_PRESS, 0, 1)[0]
        s.move_to_wake = self.read(P.CMD_PARAMETER, P.DID_MOVE_WAKE, 0, 1)[0] == 1
        flags = self.read(P.CMD_PROFILE, P.DID_LINE_RIPPLE, 0, 1)[0]
        s.track_optimization = bool(flags & 0x80)
        s.motion_sync = bool(flags & 0x04)
        s.ripple_or_jitter = bool(flags & 0x02)
        s.line_correction = bool(flags & 0x01)
        lod = self.read(P.CMD_PROFILE, P.DID_LOD_HEIGHT, 0, 1)[0]
        pair = _LOD_HW.get(self.chip)
        s.lod = pair.index(lod) if pair and lod in pair else 0
        scene = self.read(P.CMD_PROFILE, P.DID_SCENE_MODE, 0, 1)[0]
        s.scene_mode = _SCENE_HW.index(scene) if scene in _SCENE_HW else 1
        return s

    def set_settings(self, s: Settings) -> None:
        sleep = min(max(int(s.sleep_seconds), 60), 1800)  # the vendor app clamps to 1..30 minutes
        if sleep != s.sleep_seconds:
            self._log(f"sleep time clamped to {sleep}s")
        if not 1 <= s.debounce_ms <= 20:
            raise ValueError("debounce must be 1..20 ms")
        if s.scene_mode not in range(3):
            raise ValueError("scene_mode must be 0..2")
        with self.batch():
            self.write(P.CMD_PROFILE, P.DID_SLEEP_TIME, 0, P.le16(sleep))
            self.write(P.CMD_PARAMETER, P.DID_SHORT_PRESS, 0, bytes((s.debounce_ms,)))
            self.write(P.CMD_PARAMETER, P.DID_MOVE_WAKE, 0, bytes((1 if s.move_to_wake else 0,)))
            flags = ((0x80 if s.track_optimization else 0) | (0x04 if s.motion_sync else 0)
                     | (0x02 if s.ripple_or_jitter else 0) | (0x01 if s.line_correction else 0))
            self.write(P.CMD_PROFILE, P.DID_LINE_RIPPLE, 0, bytes((flags,)))
            pair = _LOD_HW.get(self.chip)
            self.write(P.CMD_PROFILE, P.DID_LOD_HEIGHT, 0, bytes((pair[s.lod] if pair else 0,)))
            self.write(P.CMD_PROFILE, P.DID_SCENE_MODE, 0, bytes((_SCENE_HW[s.scene_mode],)))

    # ------------------------------------------------------------------ buttons
    def _slot_cmd(self, wheel: bool) -> tuple[int, int]:
        return (P.CMD_WHEEL, P.WHEEL_COUNT_MAX) if wheel else (P.CMD_KEY_MATRIX, P.KEY_COUNT_MAX)

    def get_button(self, index: int, *, wheel: bool = False) -> dict:
        cmd, limit = self._slot_cmd(wheel)
        if not 0 <= index < limit:
            raise ValueError("button index out of range")
        slot = self.read(cmd, 0, index * 4, 4)
        fn = K.decode(slot)
        out = {"function": fn.name}
        if slot[0] == K.F_MACRO and not wheel:
            f = K.macro_slot_fields(slot)
            macro = self.read_macro(f["key_index"])
            macro.repeat_type, macro.assign_open = f["repeat_type"], f["assign"]
            macro.random_delay = f["random_delay"] if f["random"] else None
            name = _match_preset(macro)
            out = {"function": name or "macro"}
            if name == "fire":
                out["fire_interval"] = macro.steps[0].delay
            if not name:
                out["macro"] = macro.to_dict()
        elif fn.name.startswith("raw:"):
            out["raw"] = slot.hex()
        return out

    def set_button(self, index: int, function: str | dict, *, wheel: bool = False,
                   fire_interval: int = 50) -> None:
        cmd, limit = self._slot_cmd(wheel)
        if not 0 <= index < limit:
            raise ValueError("button index out of range")
        with self.batch():
            self._set_button(cmd, index, function, wheel, fire_interval)

    def _set_button(self, cmd: int, index: int, function: str | dict, wheel: bool,
                    fire_interval: int) -> None:
        macro = None
        if isinstance(function, dict):
            fire_interval = function.get("fire_interval", fire_interval)
            if "macro" in function:
                macro = M.Macro.from_dict(function["macro"])
            function = function["function"]
        name = function.strip().lower()
        rpt = 0
        if name in K.MACRO_ACTIONS:
            macro, rpt = M.preset(name, fire_interval=fire_interval)
        elif name in ("macro",) and macro is not None:
            rpt = macro.repeat_type
        if macro is not None:
            if wheel:
                raise ValueError("macros cannot be assigned to the scroll wheel")
            data = M.encode(macro)
            if len(macro.steps) == 0:
                slot = bytes(4)
            else:
                slot = K.macro_slot(rpt, index, assign=macro.assign_open, random_delay=macro.random_delay)
            self.write(cmd, 0, index * 4, slot)
            if len(macro.steps):
                self.write_macro(index, macro, data)
        else:
            slot = K.encode(function)
            if slot is None:
                raise ValueError(f"cannot encode {function!r}")
            self.write(cmd, 0, index * 4, slot)

    # ------------------------------------------------------------------ macros
    def read_macro(self, key_index: int) -> M.Macro:
        if not 0 <= key_index < P.KEY_COUNT_MAX:
            raise ValueError("macro slot out of range")
        first = self.read(P.CMD_MACRO, key_index, 0, P.MACRO_PAGE)
        total = (first[2] | (first[3] << 8)) + 4
        pages = total // P.MACRO_PAGE + (1 if total % P.MACRO_PAGE else 0)
        if not 0 < pages <= P.MACRO_MAX_BYTES // P.MACRO_PAGE:
            raise DeviceError(f"implausible macro length {total}")
        data = bytearray(first)
        for n in range(1, pages):
            data += self.read(P.CMD_MACRO, key_index, n * P.MACRO_PAGE, P.MACRO_PAGE)
        return M.decode(bytes(data))

    def write_macro(self, key_index: int, macro: M.Macro, data: bytes | None = None) -> None:
        if not 0 <= key_index < P.KEY_COUNT_MAX:
            raise ValueError("macro slot out of range")
        data = data if data is not None else M.encode(macro)
        for addr, chunk in M.pages(data):
            self.write(P.CMD_MACRO, key_index, addr, chunk)

    # ------------------------------------------------------------------ whole-profile snapshot
    def snapshot(self) -> dict:
        st = self.status()
        out = {"format": "ghostx-profile", "version": 1, "profile": self.get_profile(),
               "chip": st.chip, "report_rate": self.get_report_rate()}
        dpi = self.get_dpi()
        out["dpi"] = {"values": dpi.values, "enabled": dpi.enabled, "current": dpi.current,
                      "colors": dpi.colors}
        out["buttons"] = {name: self.get_button(i) for i, name in enumerate(K.BUTTONS)}
        out["wheel"] = {name: self.get_button(i, wheel=True) for i, name in enumerate(K.WHEEL)}
        s = self.get_settings()
        out["settings"] = s.__dict__.copy()
        return out

    def apply_snapshot(self, snap: dict) -> None:
        if snap.get("format") != "ghostx-profile":
            raise ValueError("not a ghostx profile file")
        with self.batch():
            if "dpi" in snap:
                d = snap["dpi"]
                self.set_dpi(values=d.get("values"), enabled=d.get("enabled"),
                             current=d.get("current"), colors=d.get("colors"))
            if "report_rate" in snap:
                self.set_report_rate(int(snap["report_rate"]))
            for i, name in enumerate(K.BUTTONS):
                if name in snap.get("buttons", {}):
                    self.set_button(i, snap["buttons"][name])
            for i, name in enumerate(K.WHEEL):
                if name in snap.get("wheel", {}):
                    self.set_button(i, snap["wheel"][name], wheel=True)
            if "settings" in snap:
                self.set_settings(Settings(**snap["settings"]))


def _match_preset(macro: M.Macro) -> str | None:
    """Recognise the vendor presets so they round-trip as readable names."""
    if not macro.steps:
        return None
    for name in K.MACRO_ACTIONS:
        ref, _ = M.preset(name)
        if macro.repeat_type != ref.repeat_type or len(ref.steps) != len(macro.steps):
            continue
        if any((a.kind, a.code, a.release, a.dpi, a.dx, a.dy) != (b.kind, b.code, b.release, b.dpi, b.dx, b.dy)
               for a, b in zip(ref.steps, macro.steps)):
            continue
        delays = {s.delay for s in macro.steps}
        if name in ("double_click", "triple_click") and delays != {60}:
            continue
        if name == "fire" and len(delays) != 1:
            continue
        if name == "aim" and delays != {200}:
            continue
        return name
    return None
