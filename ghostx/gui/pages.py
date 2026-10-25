"""The individual screens of the app."""

from __future__ import annotations

import copy
import json
import tkinter as tk
from tkinter import colorchooser, filedialog, messagebox

from .. import dpi as D
from .. import keys as K
from .. import protocol as P
from ..device import REPORT_RATES_HZ, SCENE_MODES, Settings
from . import theme as T
from .labels import CATEGORY_TITLES, MODIFIER_KEYSYMS, friendly, keysym_to_name
from .mouseview import MouseView
from .theme import px
from .widgets import (Card, ChipGrid, Chip, ColorDot, FlatButton, Segmented, Slider, Toggle, hline, label)

ZONE_MAP = {"left": (False, 0), "middle": (False, 1), "right": (False, 2), "back": (False, 3),
            "forward": (False, 4), "dpi": (False, 5), "up": (True, 0), "down": (True, 1)}
ZONE_TITLES = {"left": "Left button", "middle": "Wheel click", "right": "Right button", "back": "Back (side)",
               "forward": "Forward (side)", "dpi": "DPI button", "up": "Wheel scroll up", "down": "Wheel scroll down"}
SCENE_INFO = {
    "fire_all_out": ("Performance", "Highest sensor performance. Lowest latency and the most precise tracking; "
                                   "uses the most power. Best for competitive games."),
    "long_endurance": ("Balanced", "Balance between performance and power use. Good for daily work and most games."),
    "endurance": ("Endurance", "Basic performance with the longest battery life. Best for office use."),
}


class Page:
    key = ""
    title = ""
    subtitle = ""

    def __init__(self, app, parent):
        self.app = app
        self.frame = tk.Frame(parent, bg=T.BG)
        self.dirty = False
        self._loading = False
        self.build(self.frame)

    # -- to override
    def build(self, f) -> None:
        raise NotImplementedError

    def load(self, snap: dict) -> None:
        pass

    def make_apply(self):
        raise NotImplementedError

    def dirty_text(self) -> str:
        return "You have unsaved changes on this page"

    # -- shared
    def reload(self) -> None:
        if not self.app.snap:
            return
        self._loading = True
        try:
            self.load(self.app.snap)
        finally:
            self._loading = False
        self.dirty = False

    def touch(self, *_a) -> None:
        if self._loading:
            return
        self.dirty = True
        if self.app.pages.get(self.app.current) is self:
            self.app.refresh_footer()


def setting_row(parent, title: str, desc: str, widget_factory, bg: str = T.SURFACE, divider: bool = True):
    """Title + description on the left, control on the right."""
    row = tk.Frame(parent, bg=bg)
    row.pack(fill="x", pady=px(8))
    txt = tk.Frame(row, bg=bg)
    txt.pack(side="left", fill="x", expand=True)
    t = label(txt, title, 10, T.TEXT, True, bg=bg)
    t.pack(anchor="w")
    d = label(txt, desc, 9, T.MUTED, bg=bg, wraplength=px(420), justify="left")
    d.pack(anchor="w")
    holder = tk.Frame(row, bg=bg)
    holder.pack(side="right", padx=(px(16), 0))
    w = widget_factory(holder)
    w.pack()
    if divider:
        hline(parent).pack(fill="x")
    return row, t, d, w


# ===================================================================== Overview
class OverviewPage(Page):
    key, title, subtitle = "overview", "Overview", "Everything about your mouse at a glance"

    def build(self, f):
        f.columnconfigure(0, weight=0)
        f.columnconfigure(1, weight=1)
        left = Card(f, "Your Ghost X", "Click a button to change what it does", pad=16)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, px(16)))
        self.mouse = MouseView(left.body, on_select=lambda z: self.app.show_page("buttons", zone=z), zoom=0.8)
        self.mouse.pack()
        right = tk.Frame(f, bg=T.BG)
        right.grid(row=0, column=1, sticky="nsew")
        right.columnconfigure((0, 1), weight=1, uniform="tile")
        self.tiles = {}
        for i, (k, name) in enumerate((("battery", "Battery"), ("rate", "Polling rate"), ("dpi", "Active DPI"),
                                       ("profile", "Profile"), ("power", "Sleep after"), ("sensor", "Sensor"))):
            c = Card(right, pad=14)
            c.grid(row=i // 2, column=i % 2, sticky="nsew", padx=(0 if i % 2 == 0 else px(8), px(8) if i % 2 == 0 else 0),
                   pady=(0, px(14)))
            label(c.body, name.upper(), 8, T.FAINT, True).pack(anchor="w")
            val = label(c.body, "—", 20, T.TEXT, True)
            val.pack(anchor="w", pady=(px(4), 0))
            sub = label(c.body, "", 9, T.MUTED)
            sub.pack(anchor="w")
            self.tiles[k] = (val, sub, c)
        self.dots = tk.Canvas(self.tiles["dpi"][2].body, height=px(18), bg=T.SURFACE, highlightthickness=0, bd=0)
        self.dots.pack(anchor="w", fill="x", pady=(px(8), 0))

    def load(self, snap):
        st = self.app.status
        fn = {}
        for i, n in enumerate(K.BUTTONS):
            fn[n] = friendly(snap["buttons"][n]["function"])
        for i, n in enumerate(K.WHEEL):
            fn[n] = friendly(snap["wheel"][n]["function"])
        self.mouse.set_functions(fn)
        d = snap["dpi"]
        cur = d["current"]
        v = lambda k: self.tiles[k][0]
        s = lambda k: self.tiles[k][1]
        v("battery").configure(text=f"{st.battery}%")
        s("battery").configure(text="Charging" if st.charging else ("Link OK" if st.connected else "Dongle only"))
        v("rate").configure(text=f"{snap['report_rate']} Hz")
        s("rate").configure(text=f"Scene: {SCENE_INFO[SCENE_MODES[snap['settings']['scene_mode']]][0]}")
        val = d["values"][cur - 1] if 0 < cur <= len(d["values"]) else None
        v("dpi").configure(text=f"{val} DPI" if val else "—")
        s("dpi").configure(text=f"Stage {cur} of {sum(d['enabled'])} enabled")
        self.dots.delete("all")
        r = px(6)
        for i in range(P.MAX_DPI_GEAR):
            x = r + i * (2 * r + px(8))
            colors = d.get("colors") or []
            fill = (colors[i] if i < len(colors) else T.MUTED) if d["enabled"][i] else T.SURFACE3
            self.dots.create_oval(x - r, px(9) - r, x + r, px(9) + r, fill=fill, outline=T.TEXT if i + 1 == cur else "",
                                  width=px(2))
        v("profile").configure(text=f"{snap['profile'] + 1} of {P.PROFILE_COUNT}")
        s("profile").configure(text="Stored on the mouse")
        mins = max(1, round(snap["settings"]["sleep_seconds"] / 60))
        v("power").configure(text=f"{mins} min")
        s("power").configure(text="Wakes on movement" if snap["settings"]["move_to_wake"] else "Wakes on click")
        v("sensor").configure(text=st.chip_name)
        info = getattr(getattr(self.app.dev, "t", None), "info", None)
        s("sensor").configure(text=("2.4 GHz dongle" if info.kind == "dongle" else "USB cable") if info else "Simulated")


# ===================================================================== Buttons
class ButtonsPage(Page):
    key, title, subtitle = "buttons", "Buttons", "Choose what each button and the scroll wheel does"

    def build(self, f):
        self.staged: dict[str, object] = {}
        self.sel = "left"
        f.columnconfigure(0, weight=0)
        f.columnconfigure(1, weight=1)
        left = Card(f, pad=14)
        left.grid(row=0, column=0, sticky="n", padx=(0, px(16)))
        self.mouse = MouseView(left.body, on_select=self.select_zone, zoom=0.9)
        self.mouse.pack()

        self.panel = Card(f, pad=18)
        self.panel.grid(row=0, column=1, sticky="nsew")
        p = self.panel.body
        self.zone_title = label(p, "", 14, T.TEXT, True)
        self.zone_title.pack(anchor="w")
        self.zone_now = label(p, "", 9, T.MUTED)
        self.zone_now.pack(anchor="w", pady=(0, px(12)))

        self.cat_var = tk.StringVar()
        self.cats = [(g, CATEGORY_TITLES[g]) for g in K.ACTION_HELP]
        ChipGrid(p, self.cats, self.cat_var, command=lambda c: self.show_category(c), columns=4).pack(fill="x")
        tk.Frame(p, bg=T.SURFACE, height=px(10)).pack()
        self.fn_holder = tk.Frame(p, bg=T.SURFACE)
        self.fn_holder.pack(fill="x")
        self.fn_var = tk.StringVar()
        self.desc = label(p, "", 9, T.MUTED, wraplength=px(400), justify="left")
        self.desc.pack(anchor="w", pady=(px(10), 0))

        self.fire_row = tk.Frame(p, bg=T.SURFACE)
        label(self.fire_row, "Click interval", 10, T.TEXT, True).pack(side="left")
        self.fire_var = tk.IntVar(value=50)
        self.fire_lbl = label(self.fire_row, "50 ms", 10, T.ACCENT, True)
        self.fire_lbl.pack(side="right")
        Slider(self.fire_row, self.fire_var, 8, 300, width=170, command=self._fire_changed).pack(side="right", padx=10)

        self.custom = tk.Frame(p, bg=T.SURFACE)
        self._build_custom(self.custom)

    # ---- custom shortcut / macro panel
    def _build_custom(self, c):
        hline(c).pack(fill="x", pady=(px(4), px(12)))
        label(c, "Keyboard shortcut", 10, T.TEXT, True).pack(anchor="w")
        label(c, "Pick modifiers, then click the box and press the key", 9, T.MUTED).pack(anchor="w", pady=(0, px(8)))
        mods = tk.Frame(c, bg=T.SURFACE)
        mods.pack(anchor="w")
        self.mod_vars = {}
        for m, text in (("ctrl", "Ctrl"), ("shift", "Shift"), ("alt", "Alt"), ("win", "Win")):
            var = tk.BooleanVar()
            self.mod_vars[m] = var
            chip = Chip(mods, text, lambda v=var: (v.set(not v.get()), self._combo_changed()))
            chip.pack(side="left", padx=(0, px(6)))
            var.trace_add("write", lambda *a, ch=chip, v=var: ch.set_selected(v.get()))
        self.key_var = tk.StringVar()
        self.capture = tk.Label(c, textvariable=self.key_var, bg=T.SURFACE2, fg=T.TEXT, font=T.font(11, True),
                                width=14, pady=px(8), highlightthickness=1, highlightbackground=T.BORDER,
                                highlightcolor=T.ACCENT, takefocus=1, cursor="xterm")
        self.capture.pack(anchor="w", pady=(px(8), 0))
        self.capture.bind("<Button-1>", lambda e: (self.capture.focus_set(), self.key_var.set("press a key…")))
        self.capture.bind("<KeyPress>", self._capture_key)
        self.capture.bind("<FocusOut>", lambda e: self.key_var.get().startswith("press") and self.key_var.set(""))
        row = tk.Frame(c, bg=T.SURFACE)
        row.pack(anchor="w", pady=(px(10), 0))
        self.combo_lbl = label(row, "", 10, T.ACCENT, True)
        self.combo_lbl.pack(side="left", padx=(0, px(12)))
        FlatButton(row, "Use this shortcut", self._use_shortcut, "primary", size=9, pady=6).pack(side="left")
        hline(c).pack(fill="x", pady=px(14))
        label(c, "Macro", 10, T.TEXT, True).pack(anchor="w")
        self.macro_info = label(c, "Record or build a sequence of key presses, clicks, delays and DPI changes.",
                                9, T.MUTED, wraplength=px(400), justify="left")
        self.macro_info.pack(anchor="w")
        self.macro_btn = FlatButton(c, "Open macro editor\u2026", self._open_macros, "secondary", size=9, pady=6)
        self.macro_btn.pack(anchor="w", pady=(px(8), 0))

    def _capture_key(self, e):
        if e.keysym in MODIFIER_KEYSYMS:
            m = {"Control": "ctrl", "Shift": "shift", "Alt": "alt", "Super": "win", "Meta": "alt"}.get(e.keysym.split("_")[0])
            if m:
                self.mod_vars[m].set(True)
                self._combo_changed()
            return "break"
        name = keysym_to_name(e.keysym)
        if name is None:
            self.app.toast.show(f"'{e.keysym}' can't be assigned to a mouse button", "error", 2500)
        else:
            self.key_var.set(name)
            self._combo_changed()
        return "break"

    def _combo(self) -> str | None:
        k = self.key_var.get()
        if not k or k.startswith("press"):
            return None
        mods = [m for m, v in self.mod_vars.items() if v.get()]
        return "+".join(mods + [k])

    def _combo_changed(self):
        c = self._combo()
        self.combo_lbl.configure(text=friendly("key:" + c) if c else "")

    def _use_shortcut(self):
        c = self._combo()
        if not c:
            self.app.toast.show("Press a key first", "info", 1800)
            return
        try:
            K.parse_key_spec("key:" + c)
        except ValueError as e:
            self.app.toast.show(str(e), "error")
            return
        self.stage("key:" + c)

    def _open_macros(self):
        self.app.show_page("macros", target=self._name(self.sel) if not ZONE_MAP[self.sel][0] else None)

    # ---- state
    def _name(self, zone: str) -> str:
        wheel, i = ZONE_MAP[zone]
        return (K.WHEEL if wheel else K.BUTTONS)[i]

    def _current_spec(self, zone: str):
        if zone in self.staged:
            return self.staged[zone]
        wheel, _ = ZONE_MAP[zone]
        return self.app.snap["wheel" if wheel else "buttons"][self._name(zone)]

    @staticmethod
    def _fname(spec) -> str:
        return spec if isinstance(spec, str) else spec["function"]

    def load(self, snap):
        self.staged.clear()
        self._refresh_labels()
        self.select_zone(self.sel)

    def _refresh_labels(self):
        texts = {}
        for z in ZONE_MAP:
            name = friendly(self._fname(self._current_spec(z)))
            texts[z] = name + ("  •" if z in self.staged else "")
        self.mouse.set_functions(texts)

    def on_show(self, zone: str | None = None):
        if zone and self.app.snap:
            self.select_zone(zone)

    def select_zone(self, zone: str, **_kw):
        self.sel = zone
        self.mouse.select(zone)
        wheel, _ = ZONE_MAP[zone]
        self.zone_title.configure(text=ZONE_TITLES[zone])
        spec = self._current_spec(zone)
        fn = self._fname(spec)
        self.zone_now.configure(text=f"Currently: {friendly(fn)}" + ("  (not applied yet)" if zone in self.staged else ""))
        cat = next((g for g, items in K.ACTION_HELP.items() if any(n == fn for n, _ in items)), None)
        if fn.startswith("key:") or fn in ("macro",) or fn.startswith("raw:"):
            cat = "Custom"
        self.cat_var.set(cat or "Mouse buttons")
        self.show_category(self.cat_var.get())
        self.macro_btn.set_enabled(not wheel)

    def show_category(self, cat: str):
        for w in self.fn_holder.winfo_children():
            w.destroy()
        wheel, _ = ZONE_MAP[self.sel]
        fn = self._fname(self._current_spec(self.sel))
        self.fn_var.set(fn)
        if cat == "Custom":
            self.fn_holder.pack_forget()
            self.desc.configure(text="")
            self.fire_row.pack_forget()
            self.custom.pack(fill="x", pady=(px(4), 0))
            self.key_var.set("")
            if fn.startswith("key:"):
                parts = fn[4:].split("+")
                for m in self.mod_vars:
                    self.mod_vars[m].set(any(p in (m, "l" + m, "lgui" if m == "win" else "-") for p in parts))
                self.key_var.set(parts[-1])
            self._combo_changed()
            return
        self.custom.pack_forget()
        self.fn_holder.pack(fill="x", before=self.desc)
        items = [(n, t) for n, t in K.ACTION_HELP[cat] if n not in ("key:<combo>", "macro", "raw:xx-xx-xx-xx")]
        if wheel:
            items = [(n, t) for n, t in items if n not in K.MACRO_ACTIONS]
        self.descs = dict(items)
        ChipGrid(self.fn_holder, [(n, friendly(n)) for n, _ in items], self.fn_var,
                 command=self.stage, columns=3).pack(fill="x")
        self._show_desc(fn)

    def _show_desc(self, fn: str):
        text = next((t for g in K.ACTION_HELP.values() for n, t in g if n == fn), "")
        self.desc.configure(text=text)
        if fn == "fire":
            self.fire_row.pack(fill="x", pady=(px(14), 0))
            spec = self._current_spec(self.sel)
            self.fire_var.set(spec.get("fire_interval", 50) if isinstance(spec, dict) else 50)
            self.fire_lbl.configure(text=f"{self.fire_var.get()} ms")
        else:
            self.fire_row.pack_forget()

    def _fire_changed(self):
        self.fire_lbl.configure(text=f"{self.fire_var.get()} ms")
        self.stage({"function": "fire", "fire_interval": self.fire_var.get()}, keep_panel=True)

    def stage(self, spec, keep_panel: bool = False):
        name = self._fname(spec)
        # compare against the device value; staging the same function again clears the change
        wheel, _ = ZONE_MAP[self.sel]
        orig = self.app.snap["wheel" if wheel else "buttons"][self._name(self.sel)]
        if self._fname(orig) == name and name != "fire" and name != "macro":
            self.staged.pop(self.sel, None)
        else:
            self.staged[self.sel] = spec
        self._refresh_labels()
        self.zone_now.configure(text=f"Currently: {friendly(self._fname(orig))}" + (
            f"  →  {friendly(name)} (not applied yet)" if self.sel in self.staged else ""))
        if not keep_panel:
            self.fn_var.set(name)
            self._show_desc(name)
        self.dirty = bool(self.staged)
        self.app.refresh_footer()

    def dirty_text(self):
        n = len(self.staged)
        return f"{n} button change{'s' if n != 1 else ''} not applied yet"

    def make_apply(self):
        changes = dict(self.staged)
        dev = self.app.dev

        def fn():
            out = {"buttons": {}, "wheel": {}}
            with dev.batch():
                for zone, spec in changes.items():
                    wheel, i = ZONE_MAP[zone]
                    dev.set_button(i, spec, wheel=wheel, fire_interval=spec.get("fire_interval", 50)
                                   if isinstance(spec, dict) else 50)
            for zone in changes:
                wheel, i = ZONE_MAP[zone]
                out["wheel" if wheel else "buttons"][self._name(zone)] = dev.get_button(i, wheel=wheel)
            return out
        return fn


# ===================================================================== DPI
class DpiPage(Page):
    key, title, subtitle = "dpi", "DPI", "Up to eight sensitivity stages — the DPI button cycles through the enabled ones"

    def build(self, f):
        self.vals: list[int] = [800]
        self.en = [tk.BooleanVar(value=True) for _ in range(P.MAX_DPI_GEAR)]
        self.idx = [tk.IntVar(value=0) for _ in range(P.MAX_DPI_GEAR)]
        self.txt = [tk.StringVar() for _ in range(P.MAX_DPI_GEAR)]
        self.cur = tk.IntVar(value=1)
        self.col = ["#FFFFFF"] * P.MAX_DPI_GEAR
        self.cards, self.sliders, self.dots, self.badges, self.entries = [], [], [], [], []
        grid = tk.Frame(f, bg=T.BG)
        grid.pack(fill="x")
        for c in range(4):
            grid.columnconfigure(c, weight=1, uniform="stage")
        for i in range(P.MAX_DPI_GEAR):
            card = Card(grid, pad=14)
            card.grid(row=i // 4, column=i % 4, sticky="nsew", padx=px(6), pady=px(6))
            b = card.body
            top = tk.Frame(b, bg=T.SURFACE)
            top.pack(fill="x")
            label(top, f"STAGE {i + 1}", 8, T.FAINT, True).pack(side="left")
            Toggle(top, self.en[i], command=lambda k=i: self._toggled(k)).pack(side="right")
            row = tk.Frame(b, bg=T.SURFACE)
            row.pack(fill="x", pady=(px(8), 0))
            ent = tk.Entry(row, textvariable=self.txt[i], width=5, bg=T.SURFACE, fg=T.TEXT, relief="flat", bd=0,
                           font=T.font(22, True), insertbackground=T.TEXT, highlightthickness=0, justify="left")
            ent.pack(side="left")
            ent.bind("<Return>", lambda e, k=i: self._commit_text(k))
            ent.bind("<FocusOut>", lambda e, k=i: self._commit_text(k))
            label(row, "DPI", 9, T.MUTED).pack(side="left", padx=(px(4), 0), pady=(px(10), 0))
            sl = Slider(b, self.idx[i], 0, 100, width=170, command=lambda k=i: self._slid(k), curve=0.5)
            sl.pack(fill="x", pady=(px(4), px(6)))
            bot = tk.Frame(b, bg=T.SURFACE)
            bot.pack(fill="x")
            dot = ColorDot(bot, "#ffffff", 26, command=lambda k=i: self._pick_color(k))
            dot.pack(side="left")
            badge = FlatButton(bot, "Set active", lambda k=i: self._set_active(k), "ghost", size=9, padx=10, pady=4)
            badge.pack(side="right")
            self.cards.append(card)
            self.sliders.append(sl)
            self.dots.append(dot)
            self.badges.append(badge)
            self.entries.append(ent)
            self.en[i].trace_add("write", self.touch)
            self.idx[i].trace_add("write", self.touch)
        self.cur.trace_add("write", self.touch)
        self.note = label(f, "", 9, T.FAINT)
        self.note.pack(anchor="w", padx=px(8), pady=(px(10), 0))

    def _paint(self):
        cur = self.cur.get()
        for i, card in enumerate(self.cards):
            active = (i + 1 == cur)
            on = self.en[i].get()
            card.configure(highlightbackground=T.ACCENT if active else T.BORDER,
                           highlightcolor=T.ACCENT if active else T.BORDER)
            self.badges[i].set_text("ACTIVE" if active else "Set active")
            self.badges[i]._fg = T.ACCENT if active else T.MUTED
            self.badges[i].configure(fg=T.ACCENT if active else (T.MUTED if on else T.FAINT))
            self.sliders[i].set_enabled(on)
            self.entries[i].configure(fg=T.TEXT if on else T.FAINT, state="normal" if on else "disabled",
                                      disabledforeground=T.FAINT, disabledbackground=T.SURFACE)
            self.dots[i].set(self.col[i], dim=not on)

    def _toggled(self, i):
        self._paint()

    def _slid(self, i):
        self.txt[i].set(str(self.vals[min(len(self.vals) - 1, max(0, self.idx[i].get()))]))

    def _commit_text(self, i):
        try:
            want = int(self.txt[i].get())
        except ValueError:
            self._slid(i)
            return
        j = min(range(len(self.vals)), key=lambda k: (abs(self.vals[k] - want), k))
        self.idx[i].set(j)
        self.txt[i].set(str(self.vals[j]))

    def _set_active(self, i):
        if not self.en[i].get():
            self.en[i].set(True)
        self.cur.set(i + 1)
        self._paint()

    def _pick_color(self, i):
        c = colorchooser.askcolor(color=self.col[i], parent=self.app, title=f"Stage {i + 1} colour")[1]
        if c:
            self.col[i] = c.upper()
            self.dots[i].set(self.col[i], dim=not self.en[i].get())
            self.touch()

    def load(self, snap):
        chip = self.app.status.chip
        self.vals = sorted({e.dpi for e in D.table(chip)})
        lo, hi = self.vals[0], self.vals[-1]
        d = snap["dpi"]
        for i in range(P.MAX_DPI_GEAR):
            self.sliders[i].configure_range(0, len(self.vals) - 1)
            v = d["values"][i] or lo
            j = min(range(len(self.vals)), key=lambda k: abs(self.vals[k] - v))
            self.idx[i].set(j)
            self.txt[i].set(str(self.vals[j]))
            self.en[i].set(d["enabled"][i])
            if d.get("colors"):
                self.col[i] = d["colors"][i]
        self.cur.set(d["current"])
        self.note.configure(text=f"Sensor {self.app.status.chip_name}: {lo}–{hi} DPI. Values snap to the steps "
                                 "your sensor supports. Click a colour dot to change that stage's indicator colour.")
        self._paint()

    def dirty_text(self):
        return "DPI changes not applied yet"

    def make_apply(self):
        en = [v.get() for v in self.en]
        if not any(en):
            raise ValueError("Enable at least one DPI stage")
        cur = self.cur.get()
        if not en[cur - 1]:
            raise ValueError(f"Stage {cur} is active but switched off — pick another active stage")
        vals = [self.vals[self.idx[i].get()] for i in range(P.MAX_DPI_GEAR)]
        cols = list(self.col)
        dev = self.app.dev

        def fn():
            dev.set_dpi(values=vals, enabled=en, current=cur, colors=cols)
            d = dev.get_dpi()
            return {"dpi": {"values": d.values, "enabled": d.enabled, "current": d.current, "colors": d.colors}}
        return fn


# ===================================================================== Performance
class PerformancePage(Page):
    key, title, subtitle = "performance", "Performance", "Polling rate, sensor behaviour and power"

    def build(self, f):
        f.columnconfigure((0, 1), weight=1, uniform="perf")
        self.rate = tk.IntVar(value=1000)
        self.scene = tk.StringVar(value="long_endurance")
        self.deb = tk.IntVar(value=8)
        self.sleep = tk.IntVar(value=1)
        self.flags = {k: tk.BooleanVar() for k in ("move_to_wake", "track_optimization", "motion_sync",
                                                    "ripple_or_jitter", "line_correction")}
        self.lod = tk.IntVar(value=0)

        c = Card(f, "Polling rate", "How often the mouse reports its position. Higher is smoother and more "
                                    "responsive but uses more battery and CPU.")
        c.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, px(14)))
        row = tk.Frame(c.body, bg=T.SURFACE)
        row.pack(anchor="w")
        Segmented(row, [(hz, str(hz)) for hz in REPORT_RATES_HZ], self.rate, size=10, padx=16, pady=7).pack(side="left")
        label(row, "Hz", 10, T.MUTED).pack(side="left", padx=px(10))

        c = Card(f, "Scene mode", "Sensor power profile")
        c.grid(row=1, column=0, sticky="nsew", padx=(0, px(7)), pady=(0, px(14)))
        self.scene_cards = {}
        for key in SCENE_MODES:
            title, tip = SCENE_INFO[key]
            box = tk.Frame(c.body, bg=T.SURFACE2, highlightthickness=1, highlightbackground=T.BORDER, cursor="hand2")
            box.pack(fill="x", pady=px(4))
            t = label(box, title, 10, T.TEXT, True, bg=T.SURFACE2)
            t.pack(anchor="w", padx=px(12), pady=(px(8), 0))
            d = label(box, tip, 9, T.MUTED, bg=T.SURFACE2, wraplength=px(330), justify="left")
            d.pack(anchor="w", padx=px(12), pady=(0, px(8)))
            for w in (box, t, d):
                w.bind("<Button-1>", lambda e, k=key: self.scene.set(k))
            self.scene_cards[key] = (box, t, d)
        self.scene.trace_add("write", lambda *a: (self._paint_scene(), self.touch()))

        c = Card(f, "Timing", "Responsiveness and power saving")
        c.grid(row=1, column=1, sticky="nsew", padx=(px(7), 0), pady=(0, px(14)))
        self._slider_row(c.body, "Button debounce", "Ignores double-triggers from worn switches. Lower = faster.",
                         self.deb, 1, 20, lambda v: f"{v} ms")
        self._slider_row(c.body, "Sleep after", "Idle time before the mouse sleeps to save battery.",
                         self.sleep, 1, 30, lambda v: f"{v} min")
        row, *_ = setting_row(c.body, "Wake on movement", "Wake the mouse by moving it, not only by clicking.",
                              lambda p: Toggle(p, self.flags["move_to_wake"]), divider=False)

        self.sensor_card = Card(f, "Sensor", "Options available depend on the sensor in your mouse")
        self.sensor_card.grid(row=2, column=0, columnspan=2, sticky="ew")
        self.sensor_rows = {}
        defs = (("track_optimization", "Tracking optimisation", "Improves tracking on ripple patterns at high DPI"),
                ("motion_sync", "Motion sync", "Smoother motion reports aligned with the polling rate"),
                ("ripple_or_jitter", "Ripple control", "Smooths ripple at high DPI"),
                ("line_correction", "Line correction", "Straightens small wobbles in straight strokes"),
                ("lod", "Lift-off distance", "Height at which the sensor stops tracking"))
        for k, title, desc in defs:
            if k == "lod":
                make = lambda p: Segmented(p, [(0, "Low"), (1, "High")], self.lod, size=9, padx=14, pady=5)
            else:
                make = lambda p, k=k: Toggle(p, self.flags[k])
            row, t, d, w = setting_row(self.sensor_card.body, title, desc, make, divider=k != "lod")
            self.sensor_rows[k] = (t, d, w)
        for v in (self.rate, self.deb, self.sleep, self.lod, *self.flags.values()):
            v.trace_add("write", self.touch)

    def _slider_row(self, parent, title, desc, var, lo, hi, fmt):
        row = tk.Frame(parent, bg=T.SURFACE)
        row.pack(fill="x", pady=px(8))
        top = tk.Frame(row, bg=T.SURFACE)
        top.pack(fill="x")
        label(top, title, 10, T.TEXT, True).pack(side="left")
        value_label = label(top, fmt(var.get()), 10, T.ACCENT, True)
        value_label.pack(side="right")
        label(row, desc, 9, T.MUTED, wraplength=px(330), justify="left").pack(anchor="w")
        Slider(row, var, lo, hi, width=330).pack(anchor="w", pady=(px(4), 0))
        var.trace_add("write", lambda *a: value_label.configure(text=fmt(var.get())))
        hline(parent).pack(fill="x")

    def _paint_scene(self):
        for k, (box, t, d) in self.scene_cards.items():
            sel = k == self.scene.get()
            bg = T.ACCENT_DIM if sel else T.SURFACE2
            box.configure(bg=bg, highlightbackground=T.ACCENT if sel else T.BORDER)
            t.configure(bg=bg, fg=T.ACCENT if sel else T.TEXT)
            d.configure(bg=bg)

    def load(self, snap):
        s = snap["settings"]
        self.rate.set(snap["report_rate"])
        self.scene.set(SCENE_MODES[s["scene_mode"]])
        self.deb.set(s["debounce_ms"])
        self.sleep.set(max(1, min(30, round(s["sleep_seconds"] / 60))))
        for k, v in self.flags.items():
            v.set(bool(s[k]))
        self.lod.set(s["lod"])
        caps = self.app.caps
        supported = {"track_optimization": caps.track_optimization, "motion_sync": caps.motion_sync,
                     "ripple_or_jitter": caps.ripple or caps.jitter, "line_correction": caps.line_correction,
                     "lod": caps.lod}
        for k, (t, d, w) in self.sensor_rows.items():
            ok = supported[k]
            t.configure(fg=T.TEXT if ok else T.FAINT)
            w.set_enabled(ok)
            if k == "ripple_or_jitter":
                t.configure(text="Jitter suppression" if caps.jitter else "Ripple control")
            if k == "lod" and caps.lod:
                for v, text in zip((0, 1), caps.lod_labels):
                    w.items[v].configure(text=text)
            if not ok:
                d.configure(text="Not supported by this sensor")
        self._paint_scene()

    def dirty_text(self):
        return "Performance changes not applied yet"

    def make_apply(self):
        hz = self.rate.get()
        s = Settings(sleep_seconds=self.sleep.get() * 60, debounce_ms=self.deb.get(),
                     move_to_wake=self.flags["move_to_wake"].get(),
                     track_optimization=self.flags["track_optimization"].get(),
                     motion_sync=self.flags["motion_sync"].get(),
                     ripple_or_jitter=self.flags["ripple_or_jitter"].get(),
                     line_correction=self.flags["line_correction"].get(), lod=self.lod.get(),
                     scene_mode=SCENE_MODES.index(self.scene.get()))
        dev = self.app.dev

        def fn():
            with dev.batch():
                dev.set_report_rate(hz)
                dev.set_settings(s)
            return {"report_rate": dev.get_report_rate(), "settings": dev.get_settings().__dict__.copy()}
        return fn


# ===================================================================== Backup
class BackupPage(Page):
    key, title, subtitle = "backup", "Backup", "Save and restore everything stored in the active profile"

    def build(self, f):
        f.columnconfigure((0, 1), weight=1, uniform="bk")
        c = Card(f, "Save profile", "Writes buttons, macros, DPI stages, polling rate and settings of the "
                                    "active profile to a file you can keep or share.")
        c.grid(row=0, column=0, sticky="nsew", padx=(0, px(7)))
        FlatButton(c.body, "Save to file…", self.save, "primary").pack(anchor="w", pady=(px(6), 0))
        c = Card(f, "Restore profile", "Loads a saved file and writes it to the mouse's active profile. "
                                       "The current settings of that profile are replaced.")
        c.grid(row=0, column=1, sticky="nsew", padx=(px(7), 0))
        FlatButton(c.body, "Load from file…", self.load_file, "secondary").pack(anchor="w", pady=(px(6), 0))

    def save(self):
        if not self.app.dev:
            return
        path = filedialog.asksaveasfilename(parent=self.app, defaultextension=".json", filetypes=[("Profile", "*.json")],
                                            initialfile=f"ghostx-profile-{self.app.snap.get('profile', 0) + 1}.json")
        if not path:
            return
        data = copy.deepcopy(self.app.snap)
        try:
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2)
        except OSError as e:
            self.app.toast.show(f"Couldn't save: {e}", "error")
            return
        self.app.toast.show("Profile saved", "ok")

    def load_file(self):
        if not self.app.dev:
            return
        path = filedialog.askopenfilename(parent=self.app, filetypes=[("Profile", "*.json")])
        if not path:
            return
        try:
            with open(path, encoding="utf-8") as fh:
                snap = json.load(fh)
            if snap.get("format") != "ghostx-profile":
                raise ValueError("This isn't a Ghost X profile file")
        except (OSError, ValueError) as e:
            self.app.toast.show(str(e), "error")
            return
        if not messagebox.askyesno("Restore profile", "Write this file to the mouse's active profile?\n"
                                   "The profile's current settings will be replaced.", parent=self.app):
            return
        dev = self.app.dev

        def work():
            dev.apply_snapshot(snap)
            return dev.snapshot()

        def done(new):
            self.app.fill(new)
            self.app.toast.show("Nothing written (dry run)" if self.app.dry_run else "Profile restored", "ok")
        self.app.run_bg(work, done, "Restoring profile…")


# ===================================================================== Log
class LogPage(Page):
    key, title, subtitle = "log", "Log", "Every message exchanged with the mouse — useful for troubleshooting"

    def build(self, f):
        c = Card(f, pad=10)
        c.pack(fill="both", expand=True)
        bar = tk.Frame(c.body, bg=T.SURFACE)
        bar.pack(fill="x", pady=(0, px(8)))
        FlatButton(bar, "Copy", self._copy, "secondary", size=9, pady=5).pack(side="left")
        FlatButton(bar, "Clear", self._clear, "ghost", size=9, pady=5).pack(side="left", padx=px(8))
        self.text = tk.Text(c.body, bg=T.SURFACE, fg=T.MUTED, font=("Consolas", 9), relief="flat", bd=0,
                            highlightthickness=0, height=24, state="disabled", wrap="none", padx=4)
        self.text.pack(fill="both", expand=True)

    def append(self, line: str) -> None:
        self.text.configure(state="normal")
        self.text.insert("end", line + "\n")
        self.text.see("end")
        self.text.configure(state="disabled")

    def _copy(self):
        self.app.clipboard_clear()
        self.app.clipboard_append("\n".join(self.app.log_lines))
        self.app.toast.show("Log copied", "ok", 1500)

    def _clear(self):
        self.app.log_lines.clear()
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.configure(state="disabled")


from .macro_page import MacrosPage  # noqa: E402  (needs Page / setting_row defined above)

PAGES = {p.key: p for p in (OverviewPage, ButtonsPage, MacrosPage, DpiPage, PerformancePage, BackupPage,
                            LogPage)}
