"""Unit tests.  They only ever talk to the software model -- never to real hardware."""

import json
import unittest

from ghostx import dpi as D
from ghostx import keys as K
from ghostx import macros as M
from ghostx import protocol as P
from ghostx.device import DeviceError, GhostX, Settings
from ghostx.mock import MockTransport


def make(**kw):
    t = MockTransport(**kw)
    return GhostX(t, sleep=lambda s: None), t


class FrameTests(unittest.TestCase):
    def test_layout_matches_vendor_js(self):
        # setFeatureData(dev, cmd=6, did=0, addr=0x0102, len=3, [1,2,3]) with seq 5 ->
        # data[2]=cmd data[3]=seq data[4]=did data[5..6]=addr data[7]=len data[8..]=payload
        f = P.build_frame(65, 6, 5, 0, 0x0102, 3, b"\x01\x02\x03")
        self.assertEqual(len(f), 65)
        self.assertEqual(f[:12], bytes([6, 0, 0, 6, 5, 0, 0x02, 0x01, 3, 1, 2, 3]))

    def test_bootloader_is_refused(self):
        with self.assertRaises(P.ProtocolError):
            P.build_frame(65, P.CMD_BOOTLOADER, 1, 0, 0, 1)
        with self.assertRaises(P.ProtocolError):
            P.build_frame(65, P.CMD_BOOTLOADER | 0x80, 1, 0, 0, 1)

    def test_payload_must_fit(self):
        with self.assertRaises(P.ProtocolError):
            P.build_frame(20, 6, 1, 0, 0, 20, bytes(20))

    def test_parse_reply_with_and_without_report_id(self):
        body = bytes([6, 0, 0, 0x81, 7, 0, 0, 0, 3, 11, 22, 33]) + bytes(53)
        self.assertEqual(P.parse_reply(body, 0x81, 0, 3), bytes([11, 22, 33]))
        self.assertEqual(P.parse_reply(body[1:], 0x81, 0, 3), bytes([11, 22, 33]))
        self.assertIsNone(P.parse_reply(body, 0x82, 0, 3))            # wrong command
        self.assertIsNone(P.parse_reply(bytes(65), 0x81, 0, 3))        # length byte zero


class TransportRobustness(unittest.TestCase):
    def test_retries_over_stale_replies(self):
        dev, _ = make(stale_replies=3)
        self.assertEqual(dev.status().battery, 87)

    def test_stripped_report_id_layout(self):
        dev, _ = make(strip_report_id=True)
        self.assertEqual(dev.get_report_rate(), 1000)

    def test_gives_up_after_five_attempts(self):
        dev, _ = make(stale_replies=99)
        with self.assertRaises(DeviceError):
            dev.status()

    def test_dry_run_never_writes(self):
        t = MockTransport()
        dev = GhostX(t, dry_run=True, sleep=lambda s: None)
        dev.set_report_rate(500)
        dev.set_profile(1)
        self.assertEqual(t.writes, [])

    def test_sequence_counter_wraps(self):
        dev, t = make()
        for _ in range(300):
            dev.read(P.CMD_PROFILE, P.DID_PROFILE, 0, 1)
        self.assertTrue(all(f[P.IDX_SEQ] == (i + 1) & 0xFF for i, f in enumerate(t.sent)))


class DpiTests(unittest.TestCase):
    def test_native_and_multiplied_entries(self):
        t = D.table(0)  # sensor 3212: native 600..2400, multiplied up to 7200
        self.assertEqual(D.lookup(0, 800).hw, 21)
        e = D.lookup(0, 2500)
        self.assertEqual((e.hw, e.ratio), (33, 1))     # 2500 = 1250 * 2
        self.assertEqual(D.min_max(0), (600, 7200))
        self.assertGreater(len(t), 37)

    def test_unsupported_value(self):
        with self.assertRaises(ValueError):
            D.lookup(0, 801)
        self.assertEqual(D.nearest(0, 801).dpi, 800)

    def test_unknown_chip_falls_back_to_chip_zero(self):
        self.assertEqual(D.table(99), D.table(0))

    def test_write_payload_layout(self):
        dev, t = make(chip=6)
        dev.set_dpi(values=[800, 1200, 1600, 3200, 6400, 12800, 20000, 26000], current=3)
        cmd, did, addr, data = [w for w in t.writes if w[0] == P.CMD_DPI_VALUE][0]
        self.assertEqual((did, addr, len(data)), (0, 0, 20))
        self.assertEqual(data[0], 0xFF)                  # all stages enabled
        self.assertEqual(data[1], 3)                     # current stage
        hw = [data[2 + 2 * i] | data[3 + 2 * i] << 8 for i in range(8)]
        self.assertEqual(hw[0], D.lookup(6, 800).hw)
        self.assertEqual(dev.get_dpi().values, [800, 1200, 1600, 3200, 6400, 12800, 20000, 26000])

    def test_multiplier_roundtrip(self):
        dev, t = make(chip=0)
        dev.set_dpi(values=[800, 2500, 4800, 7200, 800, 800, 800, 800])
        self.assertEqual(dev.get_dpi().values[:4], [800, 2500, 4800, 7200])
        data = [w for w in t.writes if w[0] == P.CMD_DPI_VALUE][0][3]
        multi = data[18] | data[19] << 8
        self.assertEqual(multi & 3, 0)
        self.assertEqual((multi >> 2) & 3, 1)

    def test_rules(self):
        dev, _ = make()
        with self.assertRaises(ValueError):
            dev.set_dpi(enabled=[False] * 8)
        with self.assertRaises(ValueError):
            dev.set_dpi(enabled=[True, False] + [True] * 6, current=2)


    def test_color_byte_order_is_grb(self):
        dev, t = make()
        dev.set_dpi_colors(["#112233"] * 8)
        data = [w for w in t.writes if w[0] == P.CMD_DPI_COLOR][0][3]
        self.assertEqual(len(data), 24)
        self.assertEqual(data[:3], bytes([0x22, 0x11, 0x33]))             # G, R, B on the wire
        self.assertEqual(dev.get_dpi().colors[0], "#112233")

    def test_colors_travel_with_set_dpi_and_snapshots(self):
        dev, t = make()
        cols = ["#FF0000", "#00FF00", "#0000FF", "#FFFF00", "#FF00FF", "#00FFFF", "#FFFFFF", "#101010"]
        dev.set_dpi(colors=cols)
        self.assertEqual(dev.get_dpi().colors, cols)
        snap = dev.snapshot()
        self.assertEqual(snap["dpi"]["colors"], cols)
        dev2, _ = make()
        dev2.apply_snapshot(snap)
        self.assertEqual(dev2.get_dpi().colors, cols)

    def test_old_profile_files_without_colors_still_apply(self):
        dev, _ = make()
        before = dev.get_dpi().colors
        snap = {"format": "ghostx-profile", "version": 1, "dpi": {"values": [800] * 8, "enabled": [True] * 8,
                                                                    "current": 1}}
        dev.apply_snapshot(snap)
        self.assertEqual(dev.get_dpi().colors, before)

    def test_color_validation(self):
        dev, _ = make()
        with self.assertRaises(ValueError):
            dev.set_dpi_colors(["#112233"] * 7)
        with self.assertRaises(ValueError):
            dev.set_dpi_colors(["#12"] * 8)
        self.assertEqual(D.parse_color("f80"), "#FF8800")


class ReportRateTests(unittest.TestCase):
    def test_codes(self):
        dev, t = make()
        for hz, code in ((125, 64), (250, 32), (500, 16), (1000, 8), (2000, 4), (4000, 2), (8000, 1)):
            dev.set_report_rate(hz)
            self.assertEqual(t.space(P.CMD_REPORT_RATE)[0], code)
            self.assertEqual(dev.get_report_rate(), hz)

    def test_rejects_unknown(self):
        dev, _ = make()
        with self.assertRaises(ValueError):
            dev.set_report_rate(333)


class KeyTests(unittest.TestCase):
    def test_vendor_slots(self):
        self.assertEqual(K.encode("left_click"), bytes([1, 1, 0, 0]))
        self.assertEqual(K.encode("forward"), bytes([1, 16, 0, 0]))
        self.assertEqual(K.encode("dpi_cycle"), bytes([8, 3, 0, 0]))
        self.assertEqual(K.encode("copy"), bytes([2, 224, 6, 0]))
        self.assertEqual(K.encode("volume_up"), bytes([4, 233, 0, 0]))
        self.assertEqual(K.encode("browser"), bytes([4, 547 & 255, 547 >> 8, 0]))
        self.assertEqual(K.encode("profile_2"), bytes([9, 4, 1, 0]))
        self.assertEqual(K.encode("scroll_down"), bytes([5, 129, 0, 0]))
        self.assertEqual(K.encode("none"), bytes(4))

    def test_keyboard_spec(self):
        self.assertEqual(K.encode("key:ctrl+shift+a"), bytes([2, 224, 225, 4]))
        self.assertEqual(K.encode("key:f5"), bytes([2, 62, 0, 0]))
        with self.assertRaises(ValueError):
            K.encode("key:ctrl+shift+alt+a")
        with self.assertRaises(ValueError):
            K.encode("key:nonsense")

    def test_roundtrip_every_action(self):
        for name in K.ACTIONS:
            slot = K.encode(name)
            if slot is None:
                continue
            self.assertEqual(K.decode(slot).name if name not in ("page_up", "page_down") else name, name)

    def test_decode_unknown_is_preserved(self):
        self.assertEqual(K.decode(bytes([77, 1, 2, 3])).name, "raw:4d-01-02-03")
        self.assertEqual(K.encode("raw:4d-01-02-03"), bytes([77, 1, 2, 3]))


class HelpTests(unittest.TestCase):
    def test_every_action_is_documented(self):
        documented = {n for g in K.ACTION_HELP.values() for n, _ in g}
        self.assertEqual(set(K.ACTIONS) - documented, set())

    def test_help_command_runs_without_a_device(self):
        import contextlib
        import io
        from ghostx.cli import main
        for argv in (["help"], ["help", "functions"], ["help", "keys"], ["help", "macros"],
                     ["help", "safety"], ["help", "dpi"]):
            with contextlib.redirect_stdout(io.StringIO()) as out:
                self.assertEqual(main(argv), 0, argv)
            self.assertTrue(out.getvalue().strip())
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main(["help", "bogus"]), 2)


class MacroTests(unittest.TestCase):
    def test_encode_vendor_double_click_preset(self):
        m, rpt = M.preset("double_click")
        data = M.encode(m)
        # header: repeat 1, length-4 = 4 entries * 2 bytes = 8
        self.assertEqual(data[:4], bytes([1, 0, 8, 0]))
        self.assertEqual(data[4:], bytes([232, 60, 232, 128 | 60, 232, 60, 232, 128 | 60]))
        self.assertEqual(rpt, 0)

    def test_long_delay_forms(self):
        m = M.Macro([M.Step("key", 1000, 4), M.Step("dpi", 300, dpi=800), M.Step("move", 400, dx=-5, dy=7)])
        data = M.encode(m)
        self.assertEqual(data[4:10], bytes([4, 0, 255, 0xE8, 0x03, 0x00]))
        self.assertEqual(data[10:], bytes([250, 0x20, 0x03, 0, 255, 0x2C, 0x01, 0,
                                           254, 0, 0xFB, 0xFF, 7, 0, 255, 0x90, 0x01, 0]))
        back = M.decode(data)
        self.assertEqual([(s.kind, s.delay) for s in back.steps], [("key", 1000), ("dpi", 300), ("move", 400)])
        self.assertEqual((back.steps[2].dx, back.steps[2].dy), (-5, 7))
        self.assertEqual(M.encode(back), data)

    def test_fixed_delay_overrides_every_step(self):
        m = M.Macro.from_text("down a; delay 10\nup a; delay 90", fixed_delay=40)
        self.assertEqual(M.encode(m)[4:], bytes([4, 40, 4, 0x80 | 40]))
        self.assertEqual(M.common_delay(M.decode(M.encode(m))), 40)
        self.assertIsNone(M.common_delay(M.Macro.from_text("down a; delay 10\nup a; delay 90")))
        self.assertEqual(M.Macro.from_dict(m.to_dict()).fixed_delay, 40)

    def test_recorded_events_become_steps_with_real_gaps(self):
        steps = M.steps_from_events([(0, 4, False), (25.4, 4, True), (300, 5, False), (310, 5, True)])
        self.assertEqual([(s.code, s.release, s.delay) for s in steps],
                         [(4, False, 25), (4, True, 275), (5, False, 10), (5, True, 0)])

    def test_options_survive_a_device_round_trip(self):
        dev, t = make()
        m = M.Macro.from_text("down a; delay 80\nup a; delay 120", repeat=1, repeat_type=2, assign_open=True,
                              random_delay=15)
        dev.set_button(2, {"function": "macro", "macro": m.to_dict()})
        slot = bytes(t.space(P.CMD_KEY_MATRIX)[8:12])
        self.assertEqual(slot, bytes([K.F_MACRO, 0x80 | 2, 2, 0x80 | 15]))
        back = M.Macro.from_dict(dev.get_button(2)["macro"])
        self.assertEqual((back.repeat_type, back.assign_open, back.random_delay), (2, True, 15))

    def test_text_roundtrip(self):
        m = M.Macro.from_text("down ctrl; delay 20\npress c\nup ctrl\nclick left\nmove 3 -4\ndpi 400; delay 500")
        again = M.Macro.from_text(m.to_text())
        self.assertEqual(M.encode(m), M.encode(again))

    def test_too_long(self):
        with self.assertRaises(ValueError):
            M.encode(M.Macro([M.Step("key", 1, 4)] * 300))

    def test_random_delay_floor(self):
        m = M.Macro([M.Step("key", 10, 4)], random_delay=20)
        self.assertEqual(M.encode(m)[5], 70)  # 20 + 50

    def test_device_roundtrip_with_paging(self):
        dev, t = make()
        steps = []
        for i in range(60):   # 60 * 2 bytes + header > 32 -> several pages
            steps.append(M.Step("key", 10 + i, 4 + (i % 20), release=bool(i % 2)))
        macro = M.Macro(steps, repeat=3, repeat_type=0)
        dev.set_button(0, {"function": "macro", "macro": macro.to_dict()})
        pages = [w for w in t.writes if w[0] == P.CMD_MACRO]
        self.assertGreater(len(pages), 2)
        self.assertTrue(all(len(w[3]) <= 32 and w[2] % 32 == 0 for w in pages))
        info = dev.get_button(0)
        self.assertEqual(info["function"], "macro")
        self.assertEqual(M.encode(M.Macro.from_dict(info["macro"])), M.encode(macro))
        slot = t.space(P.CMD_KEY_MATRIX)[0:4]
        self.assertEqual(bytes(slot), bytes([K.F_MACRO, 0, 0, 0]))

    def test_presets_roundtrip_by_name(self):
        dev, _ = make()
        for name in ("double_click", "triple_click", "fire", "aim"):
            dev.set_button(1, name, fire_interval=80)
            got = dev.get_button(1)
            self.assertEqual(got["function"], name)
        self.assertEqual(got.get("fire_interval"), None)
        dev.set_button(1, "fire", fire_interval=80)
        self.assertEqual(dev.get_button(1), {"function": "fire", "fire_interval": 80})

    def test_wheel_cannot_hold_macro(self):
        dev, _ = make()
        with self.assertRaises(ValueError):
            dev.set_button(0, "double_click", wheel=True)


class SettingsAndProfile(unittest.TestCase):
    def test_settings_roundtrip(self):
        dev, t = make(chip=6)
        s = Settings(sleep_seconds=300, debounce_ms=5, move_to_wake=True, track_optimization=True,
                     motion_sync=True, ripple_or_jitter=True, line_correction=True, lod=1, scene_mode=0)
        dev.set_settings(s)
        self.assertEqual(t.space(P.CMD_PROFILE, P.DID_LINE_RIPPLE)[0], 0x80 | 4 | 2 | 1)
        self.assertEqual(t.space(P.CMD_PROFILE, P.DID_LOD_HEIGHT)[0], 2)   # 3395: hi LOD = 2
        self.assertEqual(t.space(P.CMD_PROFILE, P.DID_SCENE_MODE)[0], 1)
        self.assertEqual(dev.get_settings(), s)

    def test_sleep_is_clamped(self):
        dev, t = make()
        s = dev.get_settings()
        s.sleep_seconds = 10
        dev.set_settings(s)
        self.assertEqual(dev.get_settings().sleep_seconds, 60)

    def test_profile_switch_and_range(self):
        dev, _ = make()
        dev.set_profile(2)
        self.assertEqual(dev.get_profile(), 2)
        with self.assertRaises(ValueError):
            dev.set_profile(3)

    def test_writes_refresh_random_id_once(self):
        dev, t = make()
        before = [w for w in t.writes if w[1] == P.DID_RANDOM_ID]
        dev.set_report_rate(500)
        dev.set_report_rate(1000)
        ids = [w for w in t.writes if w[0] == P.CMD_PROFILE and w[1] == P.DID_RANDOM_ID]
        self.assertEqual(len(ids) - len(before), 2)          # one per operation, not per register
        value = ids[-1][3]
        self.assertEqual(len(value), 2)
        self.assertNotEqual(value, b"\0\0")

    def test_snapshot_roundtrip(self):
        dev, t = make()
        dev.set_button(0, "key:ctrl+shift+a")
        dev.set_button(4, "fire", fire_interval=40)
        dev.set_button(1, "scroll_left", wheel=True)
        dev.set_report_rate(2000)
        snap = dev.snapshot()
        text = json.dumps(snap)
        dev2, t2 = make(chip=6)
        dev2.apply_snapshot(json.loads(text))
        again = dev2.snapshot()
        self.assertEqual(snap, again)
        self.assertEqual(again["buttons"]["left"]["function"], "key:lctrl+lshift+a")
        self.assertEqual(again["wheel"]["down"]["function"], "scroll_left")

    def test_forbidden_command_never_reaches_device(self):
        dev, t = make()
        dev.set_profile(1)
        dev.snapshot()
        self.assertTrue(all((f[P.IDX_CMD] & 0x7F) != P.CMD_BOOTLOADER for f in t.sent))


if __name__ == "__main__":
    unittest.main()
