"""DPI tables.

The sensor exposes a per-chip table ``value -> hardware value``.  Values above the sensor's
native table are produced with a 2-bit multiplier per stage (``multiFactor``), a port of the
vendor app's ``calcMul``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from importlib import resources

CHIP_NAMES = {
    0: "3212", 1: "3220", 2: "3104", 3: "3325", 4: "3335", 5: "3370", 6: "3395", 7: "3389",
    8: "3311", 9: "S203", 10: "S205", 11: "S101UL", 12: "S301", 13: "S312", 14: "3950",
}


@dataclass(frozen=True)
class DpiEntry:
    dpi: int
    hw: int
    ratio: int | None = None  # multiplier code (1..3) or None


@lru_cache(maxsize=None)
def _raw() -> dict:
    with resources.files("ghostx").joinpath("data/dpi_tables.json").open("r", encoding="utf-8") as f:
        return json.load(f)


@lru_cache(maxsize=None)
def table(chip: int) -> tuple[DpiEntry, ...]:
    """Full table (native + multiplied entries) for a sensor chip id."""
    raw = _raw()
    key = str(chip) if str(chip) in raw else "0"  # the vendor app falls back to chip 0
    spec = raw[key]
    entries = [DpiEntry(v, hw) for v, hw in spec["dpi"]]
    step, dpi_max = spec["dpiStep"], spec["dpiMax"]

    native = list(entries)
    last_hw = native[-1].hw
    mult = 1
    value = native[-1].dpi + step * (mult + 1)
    while value <= dpi_max:
        if mult > 3:
            break
        base = value / (mult + 1)
        found = None
        for e in native:
            if e.dpi == base:
                found = e.hw
                entries.append(DpiEntry(value, e.hw, mult))
        if found == last_hw:
            mult += 1
        value += step * (mult + 1)
    return tuple(entries)


def parse_color(text: str) -> str:
    """'#f80', 'ff8800' or '#FF8800' -> '#FF8800'."""
    t = text.strip().lstrip("#")
    if len(t) == 3:
        t = "".join(c * 2 for c in t)
    if len(t) != 6 or any(c not in "0123456789abcdefABCDEF" for c in t):
        raise ValueError(f"bad colour {text!r}, expected #RRGGBB")
    return "#" + t.upper()


def min_max(chip: int) -> tuple[int, int]:
    t = table(chip)
    return t[0].dpi, max(e.dpi for e in t)


def nearest(chip: int, dpi: int) -> DpiEntry:
    return min(table(chip), key=lambda e: (abs(e.dpi - dpi), e.dpi))


def lookup(chip: int, dpi: int, *, strict: bool = True) -> DpiEntry:
    for e in table(chip):
        if e.dpi == dpi:
            return e
    if strict:
        raise ValueError(f"{dpi} DPI is not supported by sensor chip {chip}; "
                         f"nearest is {nearest(chip, dpi).dpi}")
    return nearest(chip, dpi)


def from_hardware(chip: int, hw: int, ratio_code: int) -> int | None:
    """Reverse lookup used when reading the device."""
    for e in table(chip):
        if e.hw == hw and (ratio_code == e.ratio or (ratio_code == 0 and e.ratio is None)):
            return e.dpi
    return None
