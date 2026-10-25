"""HID feature-report transports.

* :class:`WindowsHidTransport` -- pure ``ctypes`` on top of hid.dll / setupapi (no
  third-party packages).  Only device paths whose VID/PID match the Ghost X are ever
  opened.
* :class:`HidapiTransport`     -- uses the optional ``hid`` (hidapi) package on Linux/macOS.
* ``ghostx.mock.MockTransport`` -- software model of the firmware, used by the tests and
  by ``--mock`` so the app can be exercised without a mouse.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Iterable

from . import protocol as P


class TransportError(OSError):
    pass


@dataclass
class DeviceInfo:
    path: str
    vendor_id: int
    product_id: int
    usage_page: int = 0
    usage: int = 0
    feature_len: int = 0          # FeatureReportByteLength (report ID included)
    has_config_report: bool = False
    product: str = ""

    @property
    def kind(self) -> str:
        return "dongle" if self.product_id == P.PRODUCT_ID_DONGLE else "wired"


class Transport:
    """Minimal interface the protocol client needs."""

    feature_len: int = 65

    def send_feature(self, data: bytes) -> None:  # pragma: no cover - interface
        raise NotImplementedError

    def get_feature(self) -> bytes:  # pragma: no cover - interface
        raise NotImplementedError

    def close(self) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


# --------------------------------------------------------------------------------------
# Windows
# --------------------------------------------------------------------------------------
if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes as wt

    _hid = ctypes.WinDLL("hid", use_last_error=True)
    _setupapi = ctypes.WinDLL("setupapi", use_last_error=True)
    _k32 = ctypes.WinDLL("kernel32", use_last_error=True)

    class _GUID(ctypes.Structure):
        _fields_ = [("Data1", wt.DWORD), ("Data2", wt.WORD), ("Data3", wt.WORD),
                    ("Data4", ctypes.c_ubyte * 8)]

    class _SP_DEVICE_INTERFACE_DATA(ctypes.Structure):
        _fields_ = [("cbSize", wt.DWORD), ("InterfaceClassGuid", _GUID), ("Flags", wt.DWORD),
                    ("Reserved", ctypes.c_void_p)]

    class _HIDP_CAPS(ctypes.Structure):
        _fields_ = [("Usage", wt.USHORT), ("UsagePage", wt.USHORT),
                    ("InputReportByteLength", wt.USHORT), ("OutputReportByteLength", wt.USHORT),
                    ("FeatureReportByteLength", wt.USHORT), ("Reserved", wt.USHORT * 17),
                    ("NumberLinkCollectionNodes", wt.USHORT),
                    ("NumberInputButtonCaps", wt.USHORT), ("NumberInputValueCaps", wt.USHORT),
                    ("NumberInputDataIndices", wt.USHORT),
                    ("NumberOutputButtonCaps", wt.USHORT), ("NumberOutputValueCaps", wt.USHORT),
                    ("NumberOutputDataIndices", wt.USHORT),
                    ("NumberFeatureButtonCaps", wt.USHORT), ("NumberFeatureValueCaps", wt.USHORT),
                    ("NumberFeatureDataIndices", wt.USHORT)]

    class _HIDP_CAPS_ANY(ctypes.Structure):
        """Prefix of HIDP_BUTTON_CAPS / HIDP_VALUE_CAPS (both are 72 bytes)."""
        _fields_ = [("UsagePage", wt.USHORT), ("ReportID", ctypes.c_ubyte),
                    ("IsAlias", ctypes.c_ubyte), ("pad", ctypes.c_ubyte * 68)]

    class _HIDD_ATTRIBUTES(ctypes.Structure):
        _fields_ = [("Size", wt.ULONG), ("VendorID", wt.USHORT), ("ProductID", wt.USHORT),
                    ("VersionNumber", wt.USHORT)]

    _hid.HidD_GetHidGuid.argtypes = [ctypes.POINTER(_GUID)]
    _hid.HidD_GetAttributes.argtypes = [wt.HANDLE, ctypes.POINTER(_HIDD_ATTRIBUTES)]
    _hid.HidD_GetAttributes.restype = wt.BOOLEAN
    _hid.HidD_GetPreparsedData.argtypes = [wt.HANDLE, ctypes.POINTER(ctypes.c_void_p)]
    _hid.HidD_GetPreparsedData.restype = wt.BOOLEAN
    _hid.HidD_FreePreparsedData.argtypes = [ctypes.c_void_p]
    _hid.HidD_FreePreparsedData.restype = wt.BOOLEAN
    _hid.HidD_SetFeature.argtypes = [wt.HANDLE, ctypes.c_void_p, wt.ULONG]
    _hid.HidD_SetFeature.restype = wt.BOOLEAN
    _hid.HidD_GetFeature.argtypes = [wt.HANDLE, ctypes.c_void_p, wt.ULONG]
    _hid.HidD_GetFeature.restype = wt.BOOLEAN
    _hid.HidD_GetProductString.argtypes = [wt.HANDLE, ctypes.c_void_p, wt.ULONG]
    _hid.HidD_GetProductString.restype = wt.BOOLEAN
    _hid.HidP_GetCaps.argtypes = [ctypes.c_void_p, ctypes.POINTER(_HIDP_CAPS)]
    _hid.HidP_GetCaps.restype = ctypes.c_long
    for _fn in ("HidP_GetValueCaps", "HidP_GetButtonCaps"):
        getattr(_hid, _fn).argtypes = [ctypes.c_int, ctypes.POINTER(_HIDP_CAPS_ANY),
                                       ctypes.POINTER(wt.USHORT), ctypes.c_void_p]
        getattr(_hid, _fn).restype = ctypes.c_long

    _setupapi.SetupDiGetClassDevsW.argtypes = [ctypes.POINTER(_GUID), wt.LPCWSTR, wt.HWND, wt.DWORD]
    _setupapi.SetupDiGetClassDevsW.restype = ctypes.c_void_p
    _setupapi.SetupDiEnumDeviceInterfaces.argtypes = [
        ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(_GUID), wt.DWORD,
        ctypes.POINTER(_SP_DEVICE_INTERFACE_DATA)]
    _setupapi.SetupDiEnumDeviceInterfaces.restype = wt.BOOL
    _setupapi.SetupDiGetDeviceInterfaceDetailW.argtypes = [
        ctypes.c_void_p, ctypes.POINTER(_SP_DEVICE_INTERFACE_DATA), ctypes.c_void_p, wt.DWORD,
        ctypes.POINTER(wt.DWORD), ctypes.c_void_p]
    _setupapi.SetupDiGetDeviceInterfaceDetailW.restype = wt.BOOL
    _setupapi.SetupDiDestroyDeviceInfoList.argtypes = [ctypes.c_void_p]

    _k32.CreateFileW.argtypes = [wt.LPCWSTR, wt.DWORD, wt.DWORD, ctypes.c_void_p, wt.DWORD,
                                 wt.DWORD, wt.HANDLE]
    _k32.CreateFileW.restype = wt.HANDLE
    _k32.CloseHandle.argtypes = [wt.HANDLE]

    _DIGCF_PRESENT = 0x2
    _DIGCF_DEVICEINTERFACE = 0x10
    _GENERIC_READ = 0x80000000
    _GENERIC_WRITE = 0x40000000
    _SHARE_RW = 0x3
    _OPEN_EXISTING = 3
    _INVALID_HANDLE = ctypes.c_void_p(-1).value
    _HIDP_FEATURE = 2
    _HIDP_SUCCESS = 0x00110000

    def _open(path: str, access: int):
        h = _k32.CreateFileW(path, access, _SHARE_RW, None, _OPEN_EXISTING, 0, None)
        if h is None or ctypes.c_void_p(h).value == _INVALID_HANDLE:
            return None
        return h

    def _iter_hid_paths() -> Iterable[str]:
        guid = _GUID()
        _hid.HidD_GetHidGuid(ctypes.byref(guid))
        devs = _setupapi.SetupDiGetClassDevsW(ctypes.byref(guid), None, None,
                                              _DIGCF_PRESENT | _DIGCF_DEVICEINTERFACE)
        if devs is None or devs == _INVALID_HANDLE:
            return
        try:
            index = 0
            while True:
                did = _SP_DEVICE_INTERFACE_DATA()
                did.cbSize = ctypes.sizeof(did)
                if not _setupapi.SetupDiEnumDeviceInterfaces(devs, None, ctypes.byref(guid),
                                                             index, ctypes.byref(did)):
                    break
                index += 1
                needed = wt.DWORD(0)
                _setupapi.SetupDiGetDeviceInterfaceDetailW(devs, ctypes.byref(did), None, 0,
                                                           ctypes.byref(needed), None)
                size = needed.value
                if size == 0:
                    continue
                raw = ctypes.create_string_buffer(size)
                # SP_DEVICE_INTERFACE_DETAIL_DATA_W.cbSize: 8 on 64-bit, 6 on 32-bit
                ctypes.cast(raw, ctypes.POINTER(wt.DWORD))[0] = 8 if ctypes.sizeof(ctypes.c_void_p) == 8 else 6
                if not _setupapi.SetupDiGetDeviceInterfaceDetailW(devs, ctypes.byref(did), raw, size,
                                                                  None, None):
                    continue
                yield ctypes.wstring_at(ctypes.addressof(raw) + 4)
        finally:
            _setupapi.SetupDiDestroyDeviceInfoList(devs)

    def _query(path: str) -> DeviceInfo | None:
        """Read attributes/capabilities with a zero-access handle (no data is exchanged)."""
        h = _open(path, 0)
        if h is None:
            return None
        pre = ctypes.c_void_p()
        try:
            attr = _HIDD_ATTRIBUTES()
            attr.Size = ctypes.sizeof(attr)
            if not _hid.HidD_GetAttributes(h, ctypes.byref(attr)):
                return None
            info = DeviceInfo(path=path, vendor_id=attr.VendorID, product_id=attr.ProductID)
            name = ctypes.create_unicode_buffer(128)
            if _hid.HidD_GetProductString(h, name, ctypes.sizeof(name)):
                info.product = name.value
            if not _hid.HidD_GetPreparsedData(h, ctypes.byref(pre)):
                return info
            caps = _HIDP_CAPS()
            if _hid.HidP_GetCaps(pre, ctypes.byref(caps)) != _HIDP_SUCCESS:
                return info
            info.usage_page, info.usage = caps.UsagePage, caps.Usage
            info.feature_len = caps.FeatureReportByteLength
            ids = set()
            for fn, count in (("HidP_GetValueCaps", caps.NumberFeatureValueCaps),
                              ("HidP_GetButtonCaps", caps.NumberFeatureButtonCaps)):
                if count:
                    arr = (_HIDP_CAPS_ANY * count)()
                    n = wt.USHORT(count)
                    if getattr(_hid, fn)(_HIDP_FEATURE, arr, ctypes.byref(n), pre) == _HIDP_SUCCESS:
                        ids.update(arr[i].ReportID for i in range(n.value))
            info.has_config_report = P.FEATURE_REPORT_ID in ids
            return info
        finally:
            if pre:
                _hid.HidD_FreePreparsedData(pre)
            _k32.CloseHandle(h)

    def enumerate_devices() -> list[DeviceInfo]:
        """All Ghost X HID interfaces.  Paths of other vendors are never opened."""
        out = []
        needle = f"vid_{P.VENDOR_ID:04x}"
        for path in _iter_hid_paths():
            low = path.lower()
            if needle not in low or not any(f"pid_{p:04x}" in low for p in P.PRODUCT_IDS):
                continue
            info = _query(path)
            if info:
                out.append(info)
        return out

    class WindowsHidTransport(Transport):
        def __init__(self, info: DeviceInfo):
            self.info = info
            self.feature_len = info.feature_len
            self._h = _open(info.path, _GENERIC_READ | _GENERIC_WRITE)
            if self._h is None:
                err = ctypes.get_last_error()
                raise TransportError(f"cannot open {info.path} (error {err})")

        def send_feature(self, data: bytes) -> None:
            if len(data) != self.feature_len:
                raise TransportError(f"report must be {self.feature_len} bytes, got {len(data)}")
            buf = ctypes.create_string_buffer(bytes(data), len(data))
            if not _hid.HidD_SetFeature(self._h, buf, len(data)):
                raise TransportError(f"HidD_SetFeature failed (error {ctypes.get_last_error()})")

        def get_feature(self) -> bytes:
            buf = ctypes.create_string_buffer(self.feature_len)
            buf[0] = P.FEATURE_REPORT_ID
            if not _hid.HidD_GetFeature(self._h, buf, self.feature_len):
                raise TransportError(f"HidD_GetFeature failed (error {ctypes.get_last_error()})")
            return bytes(buf.raw)

        def close(self) -> None:
            if self._h is not None:
                _k32.CloseHandle(self._h)
                self._h = None

else:  # ------------------------------------------------------------------ non-Windows
    def enumerate_devices() -> list[DeviceInfo]:
        try:
            import hid  # type: ignore
        except ImportError:
            return []
        out = []
        for d in hid.enumerate(P.VENDOR_ID, 0):
            if d["product_id"] in P.PRODUCT_IDS:
                out.append(DeviceInfo(path=d["path"].decode() if isinstance(d["path"], bytes) else d["path"],
                                      vendor_id=d["vendor_id"], product_id=d["product_id"],
                                      usage_page=d.get("usage_page", 0), usage=d.get("usage", 0),
                                      feature_len=65, has_config_report=d.get("usage_page", 0) >= 0xFF00,
                                      product=d.get("product_string") or ""))
        return out

    WindowsHidTransport = None  # type: ignore


class HidapiTransport(Transport):
    """Transport on top of the optional ``hid`` package (Linux/macOS)."""

    def __init__(self, info: DeviceInfo, feature_len: int = 65):
        import hid  # type: ignore
        self.info = info
        self.feature_len = feature_len
        self._dev = hid.device()
        self._dev.open_path(info.path.encode() if isinstance(info.path, str) else info.path)

    def send_feature(self, data: bytes) -> None:
        if self._dev.send_feature_report(list(data)) < 0:
            raise TransportError("send_feature_report failed")

    def get_feature(self) -> bytes:
        data = self._dev.get_feature_report(P.FEATURE_REPORT_ID, self.feature_len)
        if not data:
            raise TransportError("get_feature_report failed")
        return bytes(data)

    def close(self) -> None:
        self._dev.close()


def open_transport(info: DeviceInfo | None = None) -> Transport:
    """Open the configuration interface of the first Ghost X found."""
    devices = enumerate_devices() if info is None else [info]
    candidates = [d for d in devices if d.has_config_report and d.feature_len >= P.IDX_DATA + 1]
    if not candidates:
        raise TransportError("no EvoFox Ghost X configuration interface found "
                             "(is the mouse / dongle plugged in?)")
    # prefer the wired connection, then the dongle
    candidates.sort(key=lambda d: d.product_id != P.PRODUCT_ID_WIRED)
    chosen = candidates[0]
    if sys.platform == "win32":
        return WindowsHidTransport(chosen)
    return HidapiTransport(chosen, chosen.feature_len or 65)


def device_signature() -> tuple:
    """Cheap fingerprint of the attached Ghost X interfaces (nothing is opened on Windows).

    Used to notice plug / unplug events without querying every device again.
    """
    if sys.platform == "win32":
        needle = f"vid_{P.VENDOR_ID:04x}"
        return tuple(sorted(p for p in _iter_hid_paths()
                            if needle in p.lower() and any(f"pid_{x:04x}" in p.lower() for x in P.PRODUCT_IDS)))
    return tuple(sorted(d.path for d in enumerate_devices()))
