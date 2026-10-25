"""Software model of the Ghost X firmware (as understood from the vendor web app).

Used by the unit tests and by ``--mock`` so the CLI/GUI can be tried without hardware.  The model
is a plain memory map addressed by ``(command, distinguish id)``.
"""

from __future__ import annotations

from . import dpi as D
from . import protocol as P
from .transport import Transport


class MockTransport(Transport):
    def __init__(self, *, chip: int = 6, feature_len: int = 65, strip_report_id: bool = False,
                 stale_replies: int = 0, battery: int = 87, charging: bool = False):
        self.feature_len = feature_len
        self.strip_report_id = strip_report_id
        self.stale_replies = stale_replies   # number of bogus replies before the real one
        self.mem: dict[tuple[int, int], bytearray] = {}
        self.writes: list[tuple[int, int, int, bytes]] = []   # (cmd, did, addr, data)
        self.sent: list[bytes] = []
        self.closed = False
        self._reply = bytes(feature_len)
        self._stale_left = stale_replies   # consumed across the whole session
        self.chip = chip
        self._reset(chip, battery, charging)

    # ---- memory helpers ------------------------------------------------------------
    def space(self, cmd: int, did: int = 0) -> bytearray:
        return self.mem.setdefault((cmd, did), bytearray(1024))

    def _put(self, cmd: int, did: int, addr: int, data: bytes) -> None:
        self.space(cmd, did)[addr:addr + len(data)] = data

    def _reset(self, chip: int, battery: int, charging: bool) -> None:
        self._put(P.CMD_CONN_BATTERY, 0, 0, bytes((1, battery | (0x80 if charging else 0), chip)))
        self._put(P.CMD_PROFILE, P.DID_PROFILE, 0, b"\0")
        self._put(P.CMD_PROFILE, P.DID_RANDOM_ID, 0, bytes(8))
        self._put(P.CMD_PROFILE, P.DID_SLEEP_TIME, 0, P.le16(60))
        self._put(P.CMD_PROFILE, P.DID_PD_TIME, 0, P.le16(10))
        self._put(P.CMD_PROFILE, P.DID_LINE_RIPPLE, 0, b"\0")
        self._put(P.CMD_PROFILE, P.DID_LOD_HEIGHT, 0, b"\0")
        self._put(P.CMD_PROFILE, P.DID_CHARGE_CNT, 0, b"\1")
        self._put(P.CMD_PROFILE, P.DID_SCENE_MODE, 0, bytes((17,)))
        self._put(P.CMD_PARAMETER, P.DID_SHORT_PRESS, 0, b"\x08")
        self._put(P.CMD_PARAMETER, P.DID_MOVE_WAKE, 0, b"\0")
        self._put(P.CMD_PARAMETER, P.DID_KEY_NUM_MAX, 0, b"\6")
        self._put(P.CMD_PARAMETER, P.DID_LED_NUM_MAX, 0, b"\x0a")
        self._put(P.CMD_REPORT_RATE, 0, 0, bytes((8,)))
        slots = [bytes((1, 1, 0, 0)), bytes((1, 4, 0, 0)), bytes((1, 2, 0, 0)), bytes((1, 8, 0, 0)),
                 bytes((1, 16, 0, 0)), bytes((8, 3, 0, 0))]
        for i, s in enumerate(slots):
            self._put(P.CMD_KEY_MATRIX, 0, i * 4, s)
        self._put(P.CMD_WHEEL, 0, 0, bytes((5, 1, 0, 0)))
        self._put(P.CMD_WHEEL, 0, 4, bytes((5, 129, 0, 0)))
        # DPI: stages 800 1200 1600 2400 3200 4800 7200 7200 (as far as the chip table allows)
        dpis = [800, 1200, 1600, 3200, 6400, 6400, 6400, 6400]
        mask, multi, body = 0xFF, 0, bytearray()
        for i, v in enumerate(dpis):
            e = D.nearest(chip, v)
            body += P.le16(e.hw)
            multi |= (e.ratio or 0) << (2 * i)
        self._put(P.CMD_DPI_VALUE, 0, 0, bytes((mask, 2)) + bytes(body) + P.le16(multi))
        cb = bytearray()
        for c in ("FC0000", "18F900", "014CEE", "EDED00", "800080", "07FFF6", "FFFFFF", "FF77BB"):
            cb += bytes((int(c[2:4], 16), int(c[0:2], 16), int(c[4:6], 16)))      # G, R, B
        self._put(P.CMD_DPI_COLOR, 0, 0, bytes(cb))
        self.writes.clear()

    # ---- Transport interface -----------------------------------------------------------
    def send_feature(self, data: bytes) -> None:
        if self.closed:
            raise OSError("closed")
        if len(data) != self.feature_len:
            raise OSError(f"bad report length {len(data)}")
        data = bytes(data)
        self.sent.append(data)
        if data[0] != P.FEATURE_REPORT_ID:
            raise OSError("unexpected report id")
        cmd, did = data[P.IDX_CMD], data[P.IDX_DID]
        addr = data[P.IDX_ADDR_LO] | (data[P.IDX_ADDR_HI] << 8)
        length = data[P.IDX_LEN]
        if (cmd & 0x7F) == P.CMD_BOOTLOADER:
            raise AssertionError("bootloader command must never be sent")
        if cmd & P.READ_FLAG:
            payload = bytes(self.space(cmd & 0x7F, did)[addr:addr + length])
            frame = bytearray(self.feature_len)
            frame[0] = P.FEATURE_REPORT_ID
            frame[P.IDX_CMD], frame[P.IDX_SEQ], frame[P.IDX_DID] = cmd, data[P.IDX_SEQ], did
            frame[P.IDX_ADDR_LO], frame[P.IDX_ADDR_HI], frame[P.IDX_LEN] = addr & 0xFF, addr >> 8, length
            frame[P.IDX_DATA:P.IDX_DATA + length] = payload
            self._reply = bytes(frame[1:]) if self.strip_report_id else bytes(frame)
        else:
            payload = data[P.IDX_DATA:P.IDX_DATA + length]
            self._put(cmd, did, addr, payload)
            self.writes.append((cmd, did, addr, bytes(payload)))

    def get_feature(self) -> bytes:
        if self._stale_left > 0:
            self._stale_left -= 1
            return bytes(self.feature_len)  # zeros: length byte 0 => rejected by the client
        return self._reply

    def close(self) -> None:
        self.closed = True
