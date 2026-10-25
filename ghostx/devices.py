"""Discovery of attached Ghost X mice (several can be connected at once: cable, dongle, more than one mouse)."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Callable

from . import protocol as P
from .transport import (DeviceInfo, Transport, TransportError, WindowsHidTransport, HidapiTransport,
                        device_signature, enumerate_devices)
import sys


@dataclass
class DeviceEntry:
    key: str                      # stable id (HID path) used to remember / re-find the device
    label: str                    # "Ghost X - USB cable"
    kind: str                     # "wired" | "dongle" | "simulated"
    open: Callable[[], Transport] = field(repr=False, compare=False)

    def __str__(self) -> str:
        return self.label


_KIND_TEXT = {"wired": "USB cable", "dongle": "2.4 GHz dongle"}


def _open_real(info: DeviceInfo) -> Transport:
    if sys.platform == "win32":
        return WindowsHidTransport(info)
    return HidapiTransport(info, info.feature_len or 65)


class RealSource:
    """Mice found through the operating system's HID stack."""

    def scan(self) -> list[DeviceEntry]:
        infos = [d for d in enumerate_devices() if d.has_config_report and d.feature_len >= P.IDX_DATA + 1]
        infos.sort(key=lambda d: (d.product_id != P.PRODUCT_ID_WIRED, d.path))   # cable first, stable order
        entries, seen = [], {}
        for d in infos:
            base = f"Ghost X - {_KIND_TEXT.get(d.kind, d.kind)}"
            seen[base] = seen.get(base, 0) + 1
            label = base if seen[base] == 1 else f"{base} #{seen[base]}"
            entries.append(DeviceEntry(d.path, label, d.kind, lambda d=d: _open_real(d)))
        # label the first of several identical devices too, so the list is unambiguous
        for e in entries:
            if sum(1 for x in entries if x.label.startswith(e.label)) > 1 and "#" not in e.label:
                e.label += " #1"
        return entries

    def signature(self) -> tuple:
        return device_signature()


class MockSource:
    """Simulated mice -- no HID access at all.  Entries can be added / removed to test hot-plug."""

    def __init__(self, count: int = 2):
        from .mock import MockTransport
        self._MockTransport = MockTransport
        self._transports: dict[str, Transport] = {}
        self.specs: list[tuple[str, str, str, dict]] = []
        presets = [("mock-usb", "Ghost X - USB cable", "wired", dict(chip=6, battery=87)),
                   ("mock-dongle", "Ghost X - 2.4 GHz dongle", "dongle", dict(chip=13, battery=46)),
                   ("mock-usb2", "Ghost X - USB cable #2", "wired", dict(chip=6, battery=64, charging=True))]
        self.specs = presets[:count]

    def _transport(self, key: str, kw: dict, kind: str) -> Transport:
        t = self._transports.get(key)
        if t is None:
            t = self._transports[key] = self._MockTransport(**kw)
            t.info = SimpleNamespace(kind=kind)
        t.closed = False            # re-opening keeps the simulated mouse's state
        return t

    def scan(self) -> list[DeviceEntry]:
        return [DeviceEntry(k, label, kind, lambda k=k, kw=kw, kind=kind: self._transport(k, kw, kind))
                for k, label, kind, kw in self.specs]

    def signature(self) -> tuple:
        return tuple(k for k, *_ in self.specs)

    # test helpers
    def unplug(self, key: str) -> None:
        self.specs = [s for s in self.specs if s[0] != key]

    def plug(self, spec: tuple) -> None:
        self.specs.append(spec)


def pick(entries: list[DeviceEntry], index: int | None = None, key: str | None = None) -> DeviceEntry:
    if not entries:
        raise TransportError("no EvoFox Ghost X configuration interface found "
                             "(is the mouse / dongle plugged in?)")
    if key is not None:
        for e in entries:
            if e.key == key:
                return e
    if index is not None:
        if not 0 <= index < len(entries):
            raise TransportError(f"device index {index} out of range (0-{len(entries) - 1}); "
                                 "see `ghostx list`")
        return entries[index]
    return entries[0]
