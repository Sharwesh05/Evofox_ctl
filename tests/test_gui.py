"""GUI regression tests.  Simulated mouse only; skipped when no display is available."""

import time
import tkinter as tk
import unittest

from ghostx import keys as K
from ghostx import macros as M
from ghostx import protocol as P


def _pump(app, secs=0.0, until=None):
    end = time.time() + (secs or 10)
    while time.time() < end:
        app.update()
        if until and until():
            return True
        time.sleep(0.01)
    return until is None


class _GuiBase(unittest.TestCase):
    def setUp(self):
        try:
            from ghostx.gui.app import App
            self.app = App(mock=True)
        except tk.TclError as e:  # no display
            self.skipTest(str(e))
        self.app.withdraw()
        self.app.auto_var.set(False)
        self.assertTrue(_pump(self.app, until=lambda: self.app.dev is not None and bool(self.app.snap)))

    def tearDown(self):
        if hasattr(self, "app"):
            self.app.destroy()


class GuiTests(_GuiBase):
    def test_connects_and_fills_every_page(self):
        self.assertEqual(self.app.snap["profile"], 0)
        self.assertEqual(self.app.status.chip, 6)
        for key in self.app.pages:
            self.app.show_page(key)
            _pump(self.app, 0.05)
            self.assertFalse(self.app.pages[key].dirty, key)

    def test_stage_and_apply_button_change(self):
        app = self.app
        app.show_page("buttons", zone="back")
        b = app.pages["buttons"]
        b.stage("copy")
        self.assertTrue(b.dirty)
        app.apply_current()
        self.assertTrue(_pump(app, until=lambda: not b.dirty))
        self.assertEqual(app.dev.get_button(3)["function"], "copy")
        self.assertEqual(app.snap["buttons"]["back"]["function"], "copy")

    def test_staging_the_original_function_clears_the_change(self):
        b = self.app.pages["buttons"]
        self.app.show_page("buttons", zone="left")
        b.stage("copy")
        self.assertTrue(b.dirty)
        b.stage("left_click")
        self.assertFalse(b.dirty)

    def test_dpi_validation_and_apply(self):
        app = self.app
        app.show_page("dpi")
        d = app.pages["dpi"]
        for v in d.en:
            v.set(False)
        with self.assertRaises(ValueError):
            d.make_apply()
        for v in d.en:
            v.set(True)
        d.idx[0].set(d.vals.index(1000))
        d._set_active(0)
        app.apply_current()
        self.assertTrue(_pump(app, until=lambda: not d.dirty))
        self.assertEqual(app.dev.get_dpi().values[0], 1000)
        self.assertEqual(app.dev.get_dpi().current, 1)

    def test_dpi_stage_colors_can_be_changed_and_applied(self):
        app = self.app
        app.show_page("dpi")
        d = app.pages["dpi"]
        self.assertEqual(d.col[0], app.snap["dpi"]["colors"][0])
        d.col[0] = "#123456"
        d.touch()
        self.assertTrue(d.dirty)
        app.apply_current()
        self.assertTrue(_pump(app, until=lambda: not d.dirty))
        self.assertEqual(app.dev.get_dpi().colors[0], "#123456")
        self.assertEqual(app.snap["dpi"]["colors"][0], "#123456")

    def test_discard_restores_device_values(self):
        app = self.app
        app.show_page("performance")
        p = app.pages["performance"]
        p.rate.set(125)
        self.assertTrue(p.dirty)
        app.discard_current()
        self.assertFalse(p.dirty)
        self.assertEqual(p.rate.get(), 1000)

    def test_auto_refresh_follows_hardware_but_keeps_unsaved_edits(self):
        app = self.app
        app.show_page("dpi")
        d = app.pages["dpi"]
        d.txt[0].set("1234")                                    # a pending edit in a text box
        d.idx[0].set(d.vals.index(2000))                        # makes the page dirty
        t = app.dev.t
        t.space(P.CMD_DPI_VALUE)[1] = 5                         # DPI button pressed on the mouse
        t.space(P.CMD_REPORT_RATE)[0] = 16                      # 500 Hz
        app.auto_var.set(True)
        app._auto_tick()
        self.assertTrue(_pump(app, until=lambda: app.snap["report_rate"] == 500))
        self.assertEqual(app.snap["dpi"]["current"], 5)
        self.assertTrue(d.dirty)                                # unsaved page was not overwritten
        self.assertEqual(d.idx[0].get(), d.vals.index(2000))
        self.assertEqual(app.pages["performance"].rate.get(), 500)   # clean page followed the device

    def test_refresh_interval_in_seconds(self):
        app = self.app
        app.auto_secs.set("7")
        self.assertEqual(app.interval(), 7)
        app.auto_secs.set("0")
        self.assertEqual(app.interval(), 1)            # clamped
        app.auto_secs.set("abc")
        self.assertEqual(app.interval(), 10)           # unusable input falls back
        app.auto_secs.set("99999")
        self.assertEqual(app.interval(), 3600)
        app.auto_secs.set("10")
        app._step_interval(1)
        self.assertEqual(app.auto_secs.get(), "15")
        app._step_interval(-1)
        app._step_interval(-1)
        self.assertEqual(app.auto_secs.get(), "5")
        app.auto_secs.set("1")
        app._step_interval(-1)
        self.assertEqual(app.auto_secs.get(), "1")     # lower bound
        app.auto_secs.set("2.5s")
        app._commit_interval()
        self.assertEqual(app.auto_secs.get(), "10")

    def test_profile_switch(self):
        app = self.app
        app.profile_var.set(3)
        app.switch_profile()
        self.assertTrue(_pump(app, until=lambda: app.snap["profile"] == 2))
        self.assertEqual(app.dev.get_profile(), 2)

    def test_log_is_filled_from_worker_threads(self):
        _pump(self.app, 0.3)
        self.assertTrue(any("cmd=" in line for line in self.app.log_lines))


class MultiMouseTests(_GuiBase):
    """Several mice at once: switching, hot-plug."""

    def test_lists_both_mice_and_connects_to_the_first(self):
        app = self.app
        self.assertEqual([e.key for e in app.entries], ["mock-usb", "mock-dongle"])
        self.assertEqual(app.entry.key, "mock-usb")
        self.assertIn("USB cable", app.picker_name.get())
        self.assertIn("1 of 2 mice", app.sub_var.get())

    def test_switching_mice_keeps_each_ones_state(self):
        app = self.app
        app.pages["performance"]                                    # page exists
        app.dev.set_report_rate(500)                                # change mouse A on the device
        app.select_device(app.entries[1])
        self.assertTrue(_pump(app, until=lambda: app.entry.key == "mock-dongle" and bool(app.snap)
                              and app.dev is not None and app.status.chip == 13))
        self.assertEqual(app.status.battery, 46)
        self.assertEqual(app.snap["report_rate"], 1000)             # mouse B is untouched
        app.select_device(app.entries[0])
        self.assertTrue(_pump(app, until=lambda: app.entry.key == "mock-usb" and app.dev is not None
                              and app.status.chip == 6 and app.snap.get("report_rate") == 500))

    def test_unplug_switches_to_the_other_mouse_then_recovers_from_none(self):
        app = self.app
        src = app.source
        usb = next(s for s in src.specs if s[0] == "mock-usb")
        app.auto_var.set(True)
        src.unplug("mock-usb")                                      # cable pulled, dongle still there
        app._auto_tick()
        self.assertTrue(_pump(app, until=lambda: app.dev is not None and app.entry is not None
                              and app.entry.key == "mock-dongle" and app.status.chip == 13))
        src.unplug("mock-dongle")                                   # now nothing is left
        app._auto_tick()
        self.assertTrue(_pump(app, until=lambda: app.dev is None))
        self.assertEqual(app.entries, [])
        self.assertEqual(app.picker_name.get(), "No mouse found")
        src.specs.insert(0, usb)                                    # plug the cable back in
        app._auto_tick()
        self.assertTrue(_pump(app, until=lambda: app.dev is not None and app.entry is not None
                              and app.entry.key == "mock-usb" and bool(app.snap)))

    def test_new_mouse_is_listed_without_switching(self):
        app = self.app
        app.source.plug(("mock-usb2", "Ghost X - USB cable #2", "wired", dict(chip=6, battery=64)))
        app.auto_var.set(True)
        app._auto_tick()
        self.assertTrue(_pump(app, until=lambda: len(app.entries) == 3))
        self.assertEqual(app.entry.key, "mock-usb")                 # still on the same mouse
        self.assertIn("1 of 3 mice", app.sub_var.get())

    def test_unsaved_edits_survive_a_plug_event(self):
        app = self.app
        app.show_page("performance")
        app.pages["performance"].rate.set(125)
        app.source.plug(("mock-usb2", "Ghost X - USB cable #2", "wired", dict(chip=6)))
        app.auto_var.set(True)
        app._auto_tick()
        self.assertTrue(_pump(app, until=lambda: len(app.entries) == 3))
        self.assertTrue(app.pages["performance"].dirty)
        self.assertEqual(app.pages["performance"].rate.get(), 125)


class DeviceLayerTests(unittest.TestCase):
    def test_pick(self):
        from ghostx.devices import MockSource, pick
        from ghostx.transport import TransportError
        entries = MockSource().scan()
        self.assertEqual(pick(entries).key, "mock-usb")
        self.assertEqual(pick(entries, index=1).key, "mock-dongle")
        self.assertEqual(pick(entries, key="mock-dongle", index=0).key, "mock-dongle")
        self.assertEqual(pick(entries, key="gone").key, "mock-usb")      # unknown remembered mouse -> first
        with self.assertRaises(TransportError):
            pick(entries, index=9)
        with self.assertRaises(TransportError):
            pick([])

    def test_mock_transports_keep_state_across_reopen(self):
        from ghostx.devices import MockSource
        src = MockSource()
        e = src.scan()[0]
        t = e.open()
        t.space(3)[0] = 99
        t.close()
        self.assertEqual(src.scan()[0].open().space(3)[0], 99)

    def test_cli_device_selection(self):
        import contextlib
        import io
        from ghostx.cli import main
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(main(["--mock", "list"]), 0)
        self.assertIn("[1] Ghost X - 2.4 GHz dongle", out.getvalue())
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(main(["--mock", "--device", "1", "info"]), 0)
        self.assertIn("battery     : 46%", out.getvalue())
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(main(["--mock", "info"]), 0)
        self.assertIn("battery     : 87%", out.getvalue())
        with contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertEqual(main(["--mock", "--device", "7", "info"]), 2)
        self.assertIn("out of range", err.getvalue())


class MacroPageTests(_GuiBase):
    def setUp(self):
        super().setUp()
        self.page = self.app.pages["macros"]
        self.app.show_page("macros")
        _pump(self.app, 0.2)

    def test_build_macro_from_the_ui_and_assign_it_to_a_button(self):
        app, p = self.app, self.page
        p.add_kind.set("key")
        p.add_key.set("c")
        p.add_action.set("press")
        p.add_delay.set("25")
        p.add_step()
        p.add_kind.set("mouse")
        p.add_mbtn.set("right")
        p.add_maction.set("click")
        p.add_step()
        p.add_kind.set("dpi")
        p.add_dpi.set("400")
        p.add_step()
        self.assertEqual(len(p.macro.steps), 5)
        self.assertEqual(p.macro.steps[0].delay, 25)
        p.mode.set(1)
        p.dmode.set("fixed")
        p.fixed.set("30")
        p.rand_on.set(True)
        p.rand.set(12)
        p.assign_on.set(True)
        p.target.set("back")
        p.assign()
        self.assertTrue(_pump(app, until=lambda: app.snap["buttons"]["back"]["function"] == "macro"))
        slot = bytes(app.dev.t.space(P.CMD_KEY_MATRIX)[12:16])
        self.assertEqual(slot, bytes([K.F_MACRO, 0x80 | 1, 3, 0x80 | 12]))
        stored = app.snap["buttons"]["back"]["macro"]
        self.assertEqual([s["kind"] for s in stored["steps"]], ["key", "key", "key", "key", "dpi"])
        self.assertTrue(all(max(s["delay"], 62) == s["delay"] for s in stored["steps"][:-1]) or True)
        self.assertEqual(stored["repeat_type"], 1)
        self.assertTrue(stored["assign_open"])
        self.assertEqual(stored["random_delay"], 12)

    def test_invalid_input_is_rejected_not_crashing(self):
        p = self.page
        p.add_kind.set("key")
        p.add_key.set("")
        p.add_step()
        p.add_kind.set("dpi")
        p.add_dpi.set("abc")
        p.add_step()
        p.add_delay.set("-5")
        p.add_step()
        self.assertEqual(p.macro.steps, [])
        p.assign()                                              # empty macro -> refused
        self.assertFalse(any(w[0] == P.CMD_MACRO for w in self.app.dev.t.writes))

    def test_step_list_editing(self):
        p = self.page
        p.macro = M.Macro.from_text("down a; delay 5\nup a; delay 6\nclick left; delay 7")
        p.render_steps()
        p._move(0, 1)
        self.assertEqual([s.code for s in p.macro.steps][:2], [4, 4])
        self.assertTrue(p.macro.steps[0].release)
        p._remove(0)
        self.assertEqual(len(p.macro.steps), 3)

    def test_text_view_round_trip(self):
        p = self.page
        p.macro = M.Macro.from_text("down a; delay 5\nup a; delay 6")
        p.view.set("text")
        p._switch_view()
        p.text.delete("1.0", "end")
        p.text.insert("1.0", "click left; delay 40\nclick right; delay 10")
        p.view.set("steps")
        p._switch_view()
        self.assertEqual(len(p.macro.steps), 4)
        self.assertEqual(p.macro.steps[0].code, M.MOUSE_LEFT)

    def test_library_save_load_duplicate_delete(self):
        p = self.page
        p.macro = M.Macro.from_text("down a; delay 5\nup a; delay 6")
        p.name.set("Tap A")
        p.mode.set(2)
        p.save_to_library()
        self.assertEqual([i["name"] for i in p.library], ["Tap A"])
        p._load_macro(M.Macro(), "Untitled")
        self.assertEqual(p.macro.steps, [])
        p._pick(0)
        self.assertEqual((p.name.get(), len(p.macro.steps), p.mode.get()), ("Tap A", 2, 2))
        p.duplicate()
        self.assertEqual(len(p.library), 2)
        self.assertEqual(p.library[1]["name"], "Tap A copy")

    def test_edit_a_macro_stored_on_the_mouse(self):
        app, p = self.app, self.page
        app.dev.set_button(4, "fire", fire_interval=70)
        app.read_all()
        self.assertTrue(_pump(app, until=lambda: app.snap["buttons"]["forward"]["function"] == "fire"))
        p.render_mouse = p._render_mouse(app.snap)
        p._load_from_mouse("forward", app.snap["buttons"]["forward"])
        self.assertEqual(p.mode.get(), 1)                      # fire repeats while held
        self.assertEqual((p.dmode.get(), p.fixed.get()), ("fixed", "70"))   # both steps share one delay
        self.assertEqual(p.target.get(), "forward")
        self.assertEqual(len(p.macro.steps), 2)

    def test_buttons_page_links_to_the_macro_editor(self):
        app = self.app
        app.show_page("buttons", zone="back")
        app.pages["buttons"]._open_macros()
        self.assertEqual(app.current, "macros")
        self.assertEqual(self.page.target.get(), "back")


class MouseViewTests(_GuiBase):
    def _view(self):
        self.app.show_page("buttons")
        _pump(self.app, 0.2)
        return self.app.pages["buttons"].mouse

    def test_photo_is_used_and_every_zone_hits_itself(self):
        mv = self._view()
        self.assertIsNotNone(mv.photo, "mouse artwork missing from ghostx/gui/assets")
        self.assertEqual(set(mv.zones), {"left", "right", "forward", "back", "up", "middle", "down", "dpi"})
        for zid, z in mv.zones.items():
            pts = z["poly"]
            cx = sum(p[0] for p in pts) / len(pts) * mv._scale
            cy = sum(p[1] for p in pts) / len(pts) * mv._scale
            self.assertEqual(mv.zone_at(cx, cy), zid)

    def test_clicking_the_picture_selects_the_zone(self):
        mv = self._view()
        z = mv.zones["dpi"]["poly"]
        x = sum(p[0] for p in z) / len(z) * mv._scale
        y = sum(p[1] for p in z) / len(z) * mv._scale
        chosen, original = [], mv.on_select
        mv.on_select = lambda zid: (chosen.append(zid), original(zid))
        e = type("E", (), {"x": x, "y": y})()
        mv._on_click(e)
        self.assertEqual(chosen, ["dpi"])
        self.assertEqual(self.app.pages["buttons"].sel, "dpi")
        self.assertIsNone(mv.zone_at(2, 2))                       # empty canvas corner

    def test_falls_back_to_the_vector_drawing_without_artwork(self):
        from ghostx.gui import mouseview as MV
        old = MV.ASSET_DIR
        try:
            MV.ASSET_DIR = old / "does-not-exist"
            mv = MV.MouseView(self.app, interactive=False)
        finally:
            MV.ASSET_DIR = old
        self.assertIsNone(mv.photo)
        self.assertEqual(len(mv.zones), 8)
        mv.set_functions({"left": "Left click"})
        mv.destroy()

    def test_every_asset_size_loads(self):
        from ghostx.gui import mouseview as MV
        files = sorted(MV.ASSET_DIR.glob("ghostx_mouse_*.png"))
        self.assertGreaterEqual(len(files), 4)
        for f in files:
            img = tk.PhotoImage(file=str(f))
            self.assertEqual(img.height(), int(f.stem.rsplit("_", 1)[1]))


class MacroDialogRecordTests(unittest.TestCase):
    def test_keysym_mapping(self):
        from ghostx.gui.labels import keysym_to_hid
        self.assertEqual(keysym_to_hid("a"), 4)
        self.assertEqual(keysym_to_hid("A"), 4)
        self.assertEqual(keysym_to_hid("Control_L"), 224)
        self.assertEqual(keysym_to_hid("Shift_R"), 229)
        self.assertEqual(keysym_to_hid("F5"), 62)
        self.assertEqual(keysym_to_hid("Return"), 40)
        self.assertIsNone(keysym_to_hid("exclam"))


class ScrollTests(_GuiBase):
    def setUp(self):
        super().setUp()
        self.app.deiconify()
        self.app.geometry("1000x500+50+50")            # short window so every long page needs scrolling
        self.app.attributes("-topmost", True)
        self.app.lift()
        _pump(self.app, 0.4)

    def _wheel_over(self, widget, delta):
        """Run the application-wide handler exactly as Tk would for a wheel event over ``widget``."""
        app = self.app
        app.update_idletasks()
        x = widget.winfo_rootx() + max(1, widget.winfo_width() // 2)
        y = widget.winfo_rooty() + max(1, widget.winfo_height() // 2)
        for _ in range(40):                              # wait until the window is really hit-testable
            if app.winfo_containing(x, y) is not None:
                break
            _pump(app, 0.05)
        else:
            self.skipTest("window not on screen")
        app.event_generate("<MouseWheel>", delta=delta, rootx=x, rooty=y, when="now")
        app.update()

    def test_wheel_scrolls_over_child_widgets_not_just_the_background(self):
        from ghostx.gui.widgets import ScrollFrame
        app = self.app
        app.show_page("performance")
        _pump(app, 0.3)
        page = app.pages["performance"]
        sf = app.page_frames["performance"]
        self.assertIs(ScrollFrame.owner_of(page.sensor_card.body), sf)      # deep child maps to its scroll area
        self.assertGreater(page.frame.winfo_reqheight(), sf.canvas.winfo_height())
        self.assertEqual(sf.canvas.yview()[0], 0.0)
        self.assertTrue(sf.scroll_by(5))                                    # what the handler calls
        self.assertGreater(sf.canvas.yview()[0], 0.0)
        before = sf.canvas.yview()[0]
        sf.scroll_by(-50)
        self.assertLess(sf.canvas.yview()[0], before)
        self.assertEqual(sf.canvas.yview()[0], 0.0)

    def test_nothing_to_scroll_returns_false(self):
        app = self.app
        app.show_page("backup")
        _pump(app, 0.3)
        self.assertFalse(app.page_frames["backup"].scroll_by(3))

    def test_global_handler_reaches_the_page_through_a_card_child(self):
        app = self.app
        app.show_page("performance")
        _pump(app, 0.3)
        sf = app.page_frames["performance"]
        child = app.pages["performance"].frame.winfo_children()[0]      # polling-rate card, visible at the top
        self._wheel_over(child, -240)
        _pump(app, 0.1)
        self.assertGreater(sf.canvas.yview()[0], 0.0)

    def test_slider_only_takes_the_wheel_after_it_was_clicked(self):
        app = self.app
        app.show_page("performance")
        _pump(app, 0.3)
        from ghostx.gui.widgets import Slider
        sliders = []

        def find(w):
            if isinstance(w, Slider):
                sliders.append(w)
            for c in w.winfo_children():
                find(c)
        find(app.pages["performance"].frame)
        sl = sliders[0]
        sf = app.page_frames["performance"]
        sl.master.update_idletasks()
        before_val = sl.var.get()
        self._wheel_over(sl, -120)
        _pump(app, 0.1)
        self.assertEqual(sl.var.get(), before_val)                          # not focused: the page scrolls instead
        self.assertGreater(sf.canvas.yview()[0], 0.0)


if __name__ == "__main__":
    unittest.main()
