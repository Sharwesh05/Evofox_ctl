"""Wire protocol of the EvoFox Ghost X configuration interface.

Recovered from the vendor web app (support.amkette.com/webapp/ghostx/).  Everything
travels in a single HID *feature report* with report ID 6.  Layout of the report as
seen by the OS (report ID included at index 0)::

    [0]  report id (6)
    [1]  0
    [2]  0
    [3]  command           (bit 7 set => read request / read response)
    [4]  sequence counter
    [5]  distinguish id    (sub-command)
    [6]  address, low byte
    [7]  address, high byte
    [8]  length            (bytes to read / bytes in payload; non-zero in a valid reply)
    [9+] payload

A write is one SET_FEATURE.  A read is one SET_FEATURE (with ``cmd | 0x80``) followed
by one GET_FEATURE whose reply echoes ``cmd | 0x80`` / distinguish id and carries the
data from index 9 on.
"""

from __future__ import annotations

VENDOR_ID = 0xB6A4
PRODUCT_ID_WIRED = 0x40B0
PRODUCT_ID_DONGLE = 0x40C1
PRODUCT_IDS = (PRODUCT_ID_WIRED, PRODUCT_ID_DONGLE)

FEATURE_REPORT_ID = 6
INPUT_REPORT_ID = 5  # unsolicited status/keys report (not needed for configuration)

# Header indices (report ID included)
IDX_CMD = 3
IDX_SEQ = 4
IDX_DID = 5
IDX_ADDR_LO = 6
IDX_ADDR_HI = 7
IDX_LEN = 8
IDX_DATA = 9

# Timing used by the vendor app (milliseconds)
DELAY_BEFORE_SET = 30
DELAY_AFTER_SET = 50
DELAY_BEFORE_GET = 80
READ_RETRIES = 5

READ_FLAG = 0x80

# Commands
CMD_CONN_BATTERY = 1
CMD_PROFILE = 2
CMD_REPORT_RATE = 3
CMD_KEY_MATRIX = 4
CMD_WHEEL = 5
CMD_DPI_VALUE = 6
CMD_DPI_COLOR = 7   # DPI indicator colours -- exists in the protocol, not used (this model has no lighting)
CMD_MACRO = 8
CMD_BACKLIGHT = 9    # back-light -- exists in the protocol, not used (this model has no lighting)
CMD_PARAMETER = 10
CMD_VERSION_REMOTE = 112  # referenced by the web app, never used
CMD_VERSION_DONGLE = 113  # referenced by the web app, never used
CMD_BOOTLOADER = 127  # firmware update mode -- deliberately NOT exposed anywhere

# Sub-commands (distinguish ids) of CMD_PROFILE
DID_RANDOM_ID = 1
DID_PROFILE = 2
DID_SLEEP_TIME = 3
DID_PD_TIME = 4
DID_LINE_RIPPLE = 5
DID_LOD_HEIGHT = 6
DID_CHARGE_CNT = 7
DID_SCENE_MODE = 8

# Sub-commands of CMD_PARAMETER
DID_KEY_NUM_MAX = 1
DID_SHORT_PRESS = 2
DID_LONG_PRESS = 3
DID_WHEEL_DEBOUNCE = 4
DID_LED_NUM_MAX = 5
DID_MOVE_WAKE = 6

KEY_COUNT_MAX = 16
WHEEL_COUNT_MAX = 4
MODE_MAXNUM = 4  # bytes per key-function slot
PROFILE_COUNT = 3
MAX_DPI_GEAR = 8
MACRO_PAGE = 32
MACRO_MAX_BYTES = 512

FORBIDDEN_COMMANDS = frozenset({CMD_BOOTLOADER})


class ProtocolError(RuntimeError):
    """Device did not answer, or answered with something unexpected."""


def build_frame(wire_len: int, cmd: int, seq: int, did: int, addr: int, length: int,
                payload: bytes = b"") -> bytes:
    """Build a feature report (report ID included) of ``wire_len`` bytes."""
    if cmd in FORBIDDEN_COMMANDS or (cmd & 0x7F) in FORBIDDEN_COMMANDS:
        raise ProtocolError("refusing to send bootloader command")
    if wire_len < IDX_DATA + 1:
        raise ProtocolError(f"feature report length {wire_len} too small")
    if len(payload) > wire_len - IDX_DATA:
        raise ProtocolError("payload does not fit in the feature report")
    if not 0 <= addr <= 0xFFFF:
        raise ProtocolError(f"address out of range: {addr}")
    if not 0 <= length <= 0xFF:
        raise ProtocolError(f"length out of range: {length}")
    buf = bytearray(wire_len)
    buf[0] = FEATURE_REPORT_ID
    buf[IDX_CMD] = cmd & 0xFF
    buf[IDX_SEQ] = seq & 0xFF
    buf[IDX_DID] = did & 0xFF
    buf[IDX_ADDR_LO] = addr & 0xFF
    buf[IDX_ADDR_HI] = (addr >> 8) & 0xFF
    buf[IDX_LEN] = length & 0xFF
    buf[IDX_DATA:IDX_DATA + len(payload)] = payload
    return bytes(buf)


def parse_reply(buf: bytes, cmd: int, did: int, length: int) -> bytes | None:
    """Validate a GET_FEATURE reply for read request (cmd|0x80, did).

    Returns the ``length`` data bytes, or ``None`` when the reply does not belong to the
    request (stale data, device busy ...).  The vendor app treats a reply as valid when
    the length byte is non-zero and cmd/did are echoed.  Some host stacks strip the
    report ID, so a layout shifted by one byte is accepted as well.
    """
    for shift in (0, 1):  # 0: report ID present, 1: report ID stripped
        need = IDX_DATA - shift + length
        if len(buf) < need:
            continue
        if (buf[IDX_LEN - shift] != 0 and buf[IDX_CMD - shift] == cmd
                and buf[IDX_DID - shift] == did):
            if shift == 0 and buf[0] != FEATURE_REPORT_ID:
                continue
            return bytes(buf[IDX_DATA - shift:IDX_DATA - shift + length])
    return None


def u16(lo: int, hi: int) -> int:
    return (lo & 0xFF) | ((hi & 0xFF) << 8)


def le16(v: int) -> bytes:
    return bytes((v & 0xFF, (v >> 8) & 0xFF))
