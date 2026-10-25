"""Macros screen: library, step editor, key recorder and all macro options."""

from __future__ import annotations

import copy
import time
import tkinter as tk
from tkinter import messagebox

from .. import keys as K
from .. import macros as M
from .. import protocol as P
from .. import settings as S
from . import theme as T
from .labels import keysym_to_hid
from .pages import Page, setting_row
from .theme import px
from .widgets import Card, FlatButton, Segmented, Slider, Toggle, hline, label

BUTTON_TITLES = {"left": "Left button", "middle": "Wheel click", "right": "Right button", "back": "Back (side)",
                 "forward": "Forward (side)", "dpi": "DPI button"}
BUTTON_SHORT = {"left": "Left", "middle": "Wheel", "right": "Right", "back": "Back", "forward": "Forward",
                "dpi": "DPI"}
MOUSE_CHOICES = [("left", "Left"), ("middle", "Middle"), ("right", "Right"), ("back", "Back"), ("forward", "Forward")]
MODE_TEXT = {0: "Repeat N times", 1: "Repeat while held", 2: "Repeat until pressed again"}


def entry(parent, var: tk.Variable, width: int = 6, justify: str = "center") -> tk.Entry:
    return tk.Entry(parent, textvariable=var, width=width, justify=justify, bg=T.SURFACE2, fg=T.TEXT,
                    insertbackground=T.TEXT, relief="flat", bd=0, font=T.font(10), highlightthickness=1,
                    highlightbackground=T.BORDER, highlightcolor=T.ACCENT, disabledbackground=T.SURFACE,
                    disabledforeground=T.FAINT)


def describe(step: M.Step) -> str:
    if step.kind == "key":
        if step.code in M._MOUSE_NAMES:
            what = f"Mouse {M._MOUSE_NAMES[step.code]}"
        else:
            what = f"Key {K.HID_NAMES.get(step.code, step.code)}"
        return f"{what}  {'release' if step.release else 'press'}"
    if step.kind == "dpi":
        return f"Set DPI to {step.dpi}"
    return f"Move pointer  X {step.dx}   Y {step.dy}"


class RecordDialog(tk.Toplevel):
    """Records keyboard presses with their real timing."""

    def __init__(self, app, on_done):
        super().__init__(app)
        self.title("Record keys")
        self.configure(bg=T.BG)
        self.transient(app)
        self.on_done = on_done
        self.events: list[tuple[float, int, bool]] = []
        self.down: set[int] = set()
        self.t0: float | None = None
        w, h = px(460), px(300)
        self.geometry(f"{w}x{h}+{app.winfo_x() + px(180)}+{app.winfo_y() + px(140)}")
        box = tk.Frame(self, bg=T.BG)
        box.pack(fill="both", expand=True, padx=px(24), pady=px(20))
        label(box, "Recording…", 16, T.TEXT, True, bg=T.BG).pack(anchor="w")
        label(box, "Press the keys you want in the macro. Each press and release is captured with its timing.\n"
                   "Press Esc or click Stop to finish.", 10, T.MUTED, bg=T.BG, justify="left",
              wraplength=px(400)).pack(anchor="w", pady=(px(6), px(14)))
        self.count_var = tk.StringVar(value="0 events")
        tk.Label(box, textvariable=self.count_var, bg=T.SURFACE, fg=T.ACCENT, font=T.font(18, True),
                 highlightthickness=1, highlightbackground=T.BORDER, pady=px(14)).pack(fill="x")
        row = tk.Frame(box, bg=T.BG)
        row.pack(fill="x", pady=px(18))
        FlatButton(row, "Stop", self._stop, "primary").pack(side="right")
        FlatButton(row, "Cancel", self._cancel, "ghost").pack(side="right", padx=px(8))
        self.bind("<KeyPress>", self._press)
        self.bind("<KeyRelease>", self._release)
        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.grab_set()
        self.focus_force()

    def _now(self) -> float:
        t = time.perf_counter() * 1000.0
        if self.t0 is None:
            self.t0 = t
        return t - self.t0

    def _press(self, e):
        if e.keysym == "Escape":
            self._stop()
            return "break"
        code = keysym_to_hid(e.keysym)
        if code is not None and code not in self.down:        # ignore keyboard auto-repeat
            self.down.add(code)
            self.events.append((self._now(), code, False))
            self.count_var.set(f"{len(self.events)} events")
        return "break"

    def _release(self, e):
        code = keysym_to_hid(e.keysym)
        if code is not None and code in self.down:
            self.down.discard(code)
            self.events.append((self._now(), code, True))
            self.count_var.set(f"{len(self.events)} events")
        return "break"

    def _stop(self):
        for code in list(self.down):                           # close keys still held
            self.events.append((self._now(), code, True))
        events = self.events
        self.destroy()
        if events:
            self.on_done(events)

    def _cancel(self):
        self.destroy()


class MacrosPage(Page):
    key, title, subtitle = "macros", "Macros", "Build or record a sequence of actions and put it on a button"

    # ------------------------------------------------------------------ build
    def build(self, f):
        self.app_library_loaded = False
        self.library: list[dict] = []
        self.lib_sel: int | None = None
        self.macro = M.Macro()
        self.modified = False
        self._building = False

        self.name = tk.StringVar(value="Untitled macro")
        self.view = tk.StringVar(value="steps")
        self.mode = tk.IntVar(value=0)
        self.count = tk.StringVar(value="1")
        self.dmode = tk.StringVar(value="actual")
        self.fixed = tk.StringVar(value="50")
        self.rand_on = tk.BooleanVar(value=False)
        self.rand = tk.IntVar(value=10)
        self.assign_on = tk.BooleanVar(value=False)
        self.target = tk.StringVar(value="left")
        self.add_kind = tk.StringVar(value="key")
        self.add_action = tk.StringVar(value="press")
        self.add_key = tk.StringVar(value="")
        self.add_mbtn = tk.StringVar(value="left")
        self.add_maction = tk.StringVar(value="click")
        self.add_dpi = tk.StringVar(value="800")
        self.add_dx = tk.StringVar(value="10")
        self.add_dy = tk.StringVar(value="0")
        self.add_delay = tk.StringVar(value="20")

        f.columnconfigure(0, weight=0)
        f.columnconfigure(1, weight=1)
        left = tk.Frame(f, bg=T.BG)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, px(16)))
        right = tk.Frame(f, bg=T.BG)
        right.grid(row=0, column=1, sticky="nsew")

        # ---- left: library + macros on the mouse
        lib = Card(left, "Library", "Macros saved on this computer", pad=14)
        lib.pack(fill="x", pady=(0, px(14)))
        lib.body.configure(width=px(250))
        self.lib_frame = tk.Frame(lib.body, bg=T.SURFACE)
        self.lib_frame.pack(fill="x")
        bar = tk.Frame(lib.body, bg=T.SURFACE)
        bar.pack(fill="x", pady=(px(10), 0))
        FlatButton(bar, "+ New", self.new_macro, "primary", size=9, padx=12, pady=5).pack(side="left")
        FlatButton(bar, "Copy", self.duplicate, "secondary", size=9, padx=12, pady=5).pack(side="left", padx=px(6))
        FlatButton(bar, "Delete", self.delete, "danger", size=9, padx=12, pady=5).pack(side="left")
        mouse = Card(left, "On the mouse", "Macros stored in the active profile", pad=14)
        mouse.pack(fill="x")
        self.mouse_frame = tk.Frame(mouse.body, bg=T.SURFACE)
        self.mouse_frame.pack(fill="x")

        # ---- right: editor
        ed = Card(right, pad=18)
        ed.pack(fill="x", pady=(0, px(14)))
        top = tk.Frame(ed.body, bg=T.SURFACE)
        top.pack(fill="x")
        label(top, "Name", 9, T.MUTED).pack(side="left")
        entry(top, self.name, 26, "left").pack(side="left", padx=px(10), ipady=px(3))
        Segmented(top, [("steps", "Steps"), ("text", "Text")], self.view, command=self._switch_view,
                  size=9, padx=12, pady=4).pack(side="right")
        tk.Frame(ed.body, bg=T.SURFACE, height=px(10)).pack()
        holder = tk.Frame(ed.body, bg=T.SURFACE)       # the Steps / Text views swap inside this holder
        holder.pack(fill="x")
        self.steps_frame = tk.Frame(holder, bg=T.SURFACE)
        self.steps_frame.pack(fill="x")
        self.text_frame = tk.Frame(holder, bg=T.SURFACE)
        self.text = tk.Text(self.text_frame, bg=T.SURFACE2, fg=T.TEXT, insertbackground=T.TEXT,
                            font=("Consolas", 11), relief="flat", highlightthickness=1,
                            highlightbackground=T.BORDER, highlightcolor=T.ACCENT, padx=px(10), pady=px(8),
                            height=12, bd=0)
        self.text.pack(fill="x")
        label(self.text_frame, "down a   up a   press a   click left   delay 30   dpi 800   move 5 -5   "
                               "(several per line with ';', '#' = comment)", 9, T.MUTED).pack(anchor="w", pady=(6, 0))
        hline(ed.body).pack(fill="x", pady=px(12))
        self._build_adder(ed.body)
        self.size_var = tk.StringVar()
        self.size_lbl = tk.Label(ed.body, textvariable=self.size_var, bg=T.SURFACE, fg=T.MUTED, font=T.font(9),
                                 anchor="w")
        self.size_lbl.pack(fill="x", pady=(px(10), 0))

        # ---- right: options
        op = Card(right, "Options", "How the mouse plays the macro", pad=18)
        op.pack(fill="x", pady=(0, px(14)))
        b = op.body
        r = tk.Frame(b, bg=T.SURFACE)
        r.pack(fill="x", pady=px(8))
        label(r, "When the button is pressed", 10, T.TEXT, True).pack(anchor="w")
        row = tk.Frame(r, bg=T.SURFACE)
        row.pack(fill="x", pady=(px(6), 0))
        Segmented(row, list(MODE_TEXT.items()), self.mode, command=self._options_changed, size=9, padx=12,
                  pady=5).pack(side="left")
        self.count_box = tk.Frame(row, bg=T.SURFACE)
        label(self.count_box, "×", 10, T.MUTED).pack(side="left", padx=(px(12), px(4)))
        entry(self.count_box, self.count, 5).pack(side="left", ipady=px(3))
        label(self.count_box, "times", 9, T.MUTED).pack(side="left", padx=px(6))
        hline(b).pack(fill="x")
        r = tk.Frame(b, bg=T.SURFACE)
        r.pack(fill="x", pady=px(8))
        label(r, "Delays between steps", 10, T.TEXT, True).pack(anchor="w")
        row = tk.Frame(r, bg=T.SURFACE)
        row.pack(fill="x", pady=(px(6), 0))
        Segmented(row, [("actual", "Each step's own delay"), ("fixed", "Same delay for every step")], self.dmode,
                  command=self._options_changed, size=9, padx=12, pady=5).pack(side="left")
        self.fixed_box = tk.Frame(row, bg=T.SURFACE)
        entry(self.fixed_box, self.fixed, 6).pack(side="left", padx=(px(12), px(4)), ipady=px(3))
        label(self.fixed_box, "ms", 9, T.MUTED).pack(side="left")
        hline(b).pack(fill="x")
        self.rand_row = setting_row(
            b, "Random delay", "Adds natural variation of up to ± the chosen milliseconds to every delay. "
            "Delays shorter than that value + 50 ms are lengthened to it.",
            lambda p: Toggle(p, self.rand_on, command=self._options_changed))
        rr = tk.Frame(b, bg=T.SURFACE)
        self.rand_slider_row = rr
        self.rand_lbl = label(rr, "± 10 ms", 10, T.ACCENT, True)
        self.rand_lbl.pack(side="right")
        Slider(rr, self.rand, 5, 100, width=300, command=self._options_changed).pack(side="left", pady=(0, px(8)))
        setting_row(b, "Assignment macro", "Pressing this button hands the macro to the left mouse button; "
                    "pressing it again takes it back.", lambda p: Toggle(p, self.assign_on,
                                                                        command=self._options_changed),
                    divider=False)

        # ---- right: use it
        use = Card(right, "Use this macro", "Put it on a button of the active profile, or keep it in your library",
                   pad=18)
        use.pack(fill="x")
        label(use.body, "Button", 10, T.TEXT, True).pack(anchor="w")
        Segmented(use.body, [(k, BUTTON_SHORT[k]) for k in K.BUTTONS], self.target, size=9, padx=14,
                  pady=5).pack(anchor="w", pady=(px(6), px(12)))
        row = tk.Frame(use.body, bg=T.SURFACE)
        row.pack(fill="x")
        FlatButton(row, "Assign to mouse", self.assign, "primary").pack(side="left")
        FlatButton(row, "Save to library", self.save_to_library, "secondary").pack(side="left", padx=px(8))
        self.note = label(use.body, "Assigning writes to the mouse right away. The wheel cannot hold a macro.", 9,
                          T.FAINT)
        self.note.pack(anchor="w", pady=(px(10), 0))

        for v in (self.name, self.mode, self.count, self.dmode, self.fixed, self.rand_on, self.rand,
                  self.assign_on):
            v.trace_add("write", self._mark)
        self.add_kind.trace_add("write", lambda *a: self._build_add_options())
        self._build_add_options()
        self._options_changed()
        self.render_steps()
        self._render_library()

    # ------------------------------------------------------------------ add-step panel
    def _build_adder(self, parent):
        label(parent, "Add a step", 10, T.TEXT, True).pack(anchor="w")
        row = tk.Frame(parent, bg=T.SURFACE)
        row.pack(fill="x", pady=(px(6), px(8)))
        Segmented(row, [("key", "Keyboard"), ("mouse", "Mouse button"), ("dpi", "DPI"), ("move", "Move")],
                  self.add_kind, size=9, padx=12, pady=5).pack(side="left")
        FlatButton(row, "●  Record keys", self.record, "danger", size=9, padx=12, pady=5).pack(side="right")
        self.add_opts = tk.Frame(parent, bg=T.SURFACE)
        self.add_opts.pack(fill="x")
        row = tk.Frame(parent, bg=T.SURFACE)
        row.pack(fill="x", pady=(px(10), 0))
        label(row, "Delay after", 9, T.MUTED).pack(side="left")
        entry(row, self.add_delay, 5).pack(side="left", padx=px(8), ipady=px(3))
        label(row, "ms", 9, T.MUTED).pack(side="left")
        FlatButton(row, "+ Add step", self.add_step, "primary", size=9, padx=14, pady=5).pack(side="right")

    def _build_add_options(self):
        for w in self.add_opts.winfo_children():
            w.destroy()
        kind = self.add_kind.get()
        o = self.add_opts
        if kind == "key":
            Segmented(o, [("press", "Press & release"), ("down", "Hold down"), ("up", "Release")], self.add_action,
                      size=9, padx=12, pady=4).pack(side="left")
            self.capture = tk.Label(o, bg=T.SURFACE2, font=T.font(10, True), width=18, pady=px(6),
                                    highlightthickness=1, highlightbackground=T.BORDER, highlightcolor=T.ACCENT,
                                    takefocus=1, cursor="xterm")
            self.capture.pack(side="left", padx=px(12))
            self.capture.bind("<Button-1>", lambda e: (self.capture.focus_set(), self.add_key.set("press a key…")))
            self.capture.bind("<KeyPress>", self._capture)
            self.capture.bind("<FocusOut>", lambda e: self.add_key.get().startswith("press") and self.add_key.set(""))
            self._key_trace = self.add_key.trace_add("write", lambda *a: self._show_key())
            self.capture.bind("<Destroy>", lambda e: e.widget is self.capture and self.add_key.trace_remove(
                "write", self._key_trace))
            self._show_key()
        elif kind == "mouse":
            Segmented(o, MOUSE_CHOICES, self.add_mbtn, size=9, padx=10, pady=4).pack(side="left")
            Segmented(o, [("click", "Click"), ("down", "Hold down"), ("up", "Release")], self.add_maction, size=9,
                      padx=10, pady=4).pack(side="left", padx=px(12))
        elif kind == "dpi":
            label(o, "Switch the sensor to", 9, T.MUTED).pack(side="left")
            entry(o, self.add_dpi, 7).pack(side="left", padx=px(8), ipady=px(3))
            label(o, "DPI", 9, T.MUTED).pack(side="left")
        else:
            label(o, "Move by  X", 9, T.MUTED).pack(side="left")
            entry(o, self.add_dx, 6).pack(side="left", padx=px(6), ipady=px(3))
            label(o, "Y", 9, T.MUTED).pack(side="left")
            entry(o, self.add_dy, 6).pack(side="left", padx=px(6), ipady=px(3))
            label(o, "counts (negative = left / up)", 9, T.MUTED).pack(side="left", padx=px(6))

    def _show_key(self):
        v = self.add_key.get()
        self.capture.configure(text=v or "click here, then press a key", fg=T.TEXT if v and not v.startswith("press")
                               else T.MUTED)

    def _capture(self, e):
        code = keysym_to_hid(e.keysym)
        if code is None:
            self.app.toast.show(f"'{e.keysym}' can't be used in a macro", "error", 2500)
        else:
            self.add_key.set(K.HID_NAMES.get(code, str(code)))
        return "break"

    def _int(self, var: tk.StringVar, name: str, lo: int, hi: int) -> int:
        try:
            v = int(float(var.get()))
        except ValueError:
            raise ValueError(f"{name} must be a number")
        if not lo <= v <= hi:
            raise ValueError(f"{name} must be between {lo} and {hi}")
        return v

    def add_step(self):
        try:
            delay = self._int(self.add_delay, "Delay", 0, 600000)
            kind = self.add_kind.get()
            new: list[M.Step] = []
            if kind == "key":
                name = self.add_key.get().strip()
                if not name or name.startswith("press"):
                    raise ValueError("Click the key box and press a key first")
                code = K.HID_KEYS.get(name)
                if code is None:
                    raise ValueError(f"Unknown key {name!r}")
                new = self._pair(code, self.add_action.get(), delay)
            elif kind == "mouse":
                code = M.MOUSE_BUTTON_CODES[self.add_mbtn.get()]
                new = self._pair(code, self.add_maction.get(), delay)
            elif kind == "dpi":
                new = [M.Step("dpi", delay, dpi=self._int(self.add_dpi, "DPI", 50, 30000))]
            else:
                new = [M.Step("move", delay, dx=self._int(self.add_dx, "X", -32767, 32767),
                              dy=self._int(self.add_dy, "Y", -32767, 32767))]
        except ValueError as e:
            self.app.toast.show(str(e), "error", 3000)
            return
        self.macro.steps.extend(new)
        self._mark()
        self.render_steps()

    @staticmethod
    def _pair(code: int, action: str, delay: int) -> list[M.Step]:
        if action in ("press", "click"):
            return [M.Step("key", delay, code), M.Step("key", 0, code, release=True)]
        return [M.Step("key", delay, code, release=(action == "up"))]

    # ------------------------------------------------------------------ steps list
    def render_steps(self):
        for w in self.steps_frame.winfo_children():
            w.destroy()
        steps = self.macro.steps
        if not steps:
            label(self.steps_frame, "No steps yet — add some below, or press Record keys.", 10, T.MUTED).pack(
                anchor="w", pady=px(6))
        else:
            head = tk.Frame(self.steps_frame, bg=T.SURFACE)
            head.pack(fill="x")
            label(head, "#", 8, T.FAINT, True).pack(side="left", padx=(px(8), 0))
            label(head, "ACTION", 8, T.FAINT, True).pack(side="left", padx=px(24))
            label(head, "DELAY AFTER", 8, T.FAINT, True).pack(side="right", padx=(0, px(120)))
        for i, s in enumerate(steps):
            self._row(i, s)
        self._update_size()

    def _row(self, i: int, s: M.Step):
        row = tk.Frame(self.steps_frame, bg=T.SURFACE2, highlightthickness=1, highlightbackground=T.BORDER)
        row.pack(fill="x", pady=px(2))
        label(row, str(i + 1), 9, T.FAINT, bg=T.SURFACE2, width=3).pack(side="left", padx=(px(8), 0), pady=px(6))
        label(row, describe(s), 10, T.TEXT, bg=T.SURFACE2).pack(side="left", padx=px(10))
        btns = tk.Frame(row, bg=T.SURFACE2)
        btns.pack(side="right", padx=px(6))
        for text, cmd in (("↑", lambda i=i: self._move(i, -1)), ("↓", lambda i=i: self._move(i, 1)),
                          ("✕", lambda i=i: self._remove(i))):
            FlatButton(btns, text, cmd, "ghost", size=9, padx=7, pady=3).pack(side="left")
        var = tk.StringVar(value=str(s.delay))
        fixed = self.dmode.get() == "fixed"
        e = entry(row, var, 6)
        e.pack(side="right", padx=(0, px(10)), ipady=px(2))
        if fixed:
            e.configure(state="disabled")
        label(row, "ms", 9, T.MUTED, bg=T.SURFACE2).pack(side="right")

        def commit(_e=None, s=s, var=var):
            try:
                v = max(0, min(600000, int(float(var.get()))))
            except ValueError:
                var.set(str(s.delay))
                return
            var.set(str(v))
            if v != s.delay:
                s.delay = v
                self._mark()
        e.bind("<Return>", commit)
        e.bind("<FocusOut>", commit)

    def _move(self, i: int, d: int):
        j = i + d
        if 0 <= j < len(self.macro.steps):
            st = self.macro.steps
            st[i], st[j] = st[j], st[i]
            self._mark()
            self.render_steps()

    def _remove(self, i: int):
        self.macro.steps.pop(i)
        self._mark()
        self.render_steps()

    # ------------------------------------------------------------------ options / state
    def _options_changed(self, *_):
        if self.mode.get() == 0:
            self.count_box.pack(side="left")
        else:
            self.count_box.pack_forget()
        if self.dmode.get() == "fixed":
            self.fixed_box.pack(side="left")
        else:
            self.fixed_box.pack_forget()
        if self.rand_on.get():
            self.rand_slider_row.pack(fill="x", after=self.rand_row[0])
            self.rand_lbl.configure(text=f"± {self.rand.get()} ms")
        else:
            self.rand_slider_row.pack_forget()
        if hasattr(self, "steps_frame") and not self._building:
            self.render_steps()           # delay boxes are disabled in 'same delay' mode

    def _mark(self, *_):
        if self._building:
            return
        self.modified = True
        self._update_size()

    def _collect(self) -> M.Macro:
        """Build the macro from the editor (raises ValueError with a readable message)."""
        if self.view.get() == "text":
            self._read_text()
        rep = self._int(self.count, "Repeat count", 1, 65535) if self.mode.get() == 0 else 1
        fixed = self._int(self.fixed, "Delay", 0, 600000) if self.dmode.get() == "fixed" else None
        m = M.Macro(steps=[M.Step(**s.__dict__) for s in self.macro.steps], repeat=rep, repeat_type=self.mode.get(),
                    assign_open=self.assign_on.get(), random_delay=self.rand.get() if self.rand_on.get() else None,
                    fixed_delay=fixed)
        return m

    def _update_size(self):
        try:
            n = len(M.encode(self._collect_quiet()))
            ok = n <= M.MAX_BYTES
            self.size_var.set(f"{len(self.macro.steps)} steps · {n} of {M.MAX_BYTES} bytes of macro memory"
                              + ("" if ok else "  — too long!"))
            self.size_lbl.configure(fg=T.MUTED if ok else T.DANGER)
        except ValueError as e:
            self.size_var.set(str(e))
            self.size_lbl.configure(fg=T.DANGER)

    def _collect_quiet(self) -> M.Macro:
        try:
            rep = max(1, min(65535, int(float(self.count.get())))) if self.mode.get() == 0 else 1
        except ValueError:
            rep = 1
        try:
            fixed = max(0, int(float(self.fixed.get()))) if self.dmode.get() == "fixed" else None
        except ValueError:
            fixed = None
        return M.Macro(steps=self.macro.steps, repeat=rep, repeat_type=self.mode.get(),
                       random_delay=self.rand.get() if self.rand_on.get() else None, fixed_delay=fixed)

    # ------------------------------------------------------------------ text view
    def _switch_view(self):
        if self.view.get() == "text":
            self.text.delete("1.0", "end")
            self.text.insert("1.0", M.Macro(steps=self.macro.steps).to_text())
            self.steps_frame.pack_forget()
            self.text_frame.pack(fill="x")
        else:
            try:
                self._read_text()
            except ValueError as e:
                self.app.toast.show(str(e), "error", 3500)
                self.view.set("text")
                return
            self.text_frame.pack_forget()
            self.steps_frame.pack(fill="x")
            self.render_steps()

    def _read_text(self):
        parsed = M.Macro.from_text(self.text.get("1.0", "end"))
        M.encode(parsed)
        if [s.__dict__ for s in parsed.steps] != [s.__dict__ for s in self.macro.steps]:
            self.macro.steps = parsed.steps
            self._mark()

    # ------------------------------------------------------------------ loading / library
    def _load_macro(self, m: M.Macro, name: str | None = None, lib_index: int | None = None):
        self._building = True
        try:
            self.macro = M.Macro(steps=[M.Step(**s.__dict__) for s in m.steps])
            if name is not None:
                self.name.set(name)
            self.mode.set(m.repeat_type)
            self.count.set(str(m.repeat))
            fixed = m.fixed_delay if m.fixed_delay is not None else None
            self.dmode.set("fixed" if fixed is not None else "actual")
            if fixed is not None:
                self.fixed.set(str(fixed))
            self.rand_on.set(m.random_delay is not None)
            if m.random_delay:
                self.rand.set(max(5, min(100, m.random_delay)))
            self.assign_on.set(m.assign_open)
            self.lib_sel = lib_index
            if self.view.get() == "text":
                self.view.set("steps")
                self.text_frame.pack_forget()
                self.steps_frame.pack(fill="x")
        finally:
            self._building = False
        self.modified = False
        self._options_changed()
        self.render_steps()
        self._render_library()

    def _confirm_discard(self) -> bool:
        return (not self.modified or not self.macro.steps or messagebox.askyesno(
            "Unsaved macro", "Discard the changes to the macro you are editing?", parent=self.app))

    def new_macro(self):
        if not self._confirm_discard():
            return
        self._load_macro(M.Macro(), "Untitled macro")

    def _library_path_enabled(self) -> bool:
        return not self.app.mock

    def _persist(self):
        if self._library_path_enabled():
            S.save_macro_library(self.library)

    def save_to_library(self):
        try:
            m = self._collect()
        except ValueError as e:
            self.app.toast.show(str(e), "error", 3500)
            return
        name = self.name.get().strip() or "Untitled macro"
        item = {"name": name, "macro": m.to_dict()}
        if self.lib_sel is not None and 0 <= self.lib_sel < len(self.library):
            self.library[self.lib_sel] = item
        else:
            self.library.append(item)
            self.lib_sel = len(self.library) - 1
        self.modified = False
        self._persist()
        self._render_library()
        self.app.toast.show(f"Saved “{name}” to the library", "ok", 2200)

    def duplicate(self):
        if self.lib_sel is None or not (0 <= self.lib_sel < len(self.library)):
            self.app.toast.show("Select a saved macro first", "info", 2000)
            return
        item = copy.deepcopy(self.library[self.lib_sel])
        item["name"] += " copy"
        self.library.append(item)
        self._persist()
        self._load_macro(M.Macro.from_dict(item["macro"]), item["name"], len(self.library) - 1)

    def delete(self):
        if self.lib_sel is None or not (0 <= self.lib_sel < len(self.library)):
            self.app.toast.show("Select a saved macro first", "info", 2000)
            return
        name = self.library[self.lib_sel]["name"]
        if not messagebox.askyesno("Delete macro", f"Delete “{name}” from the library?", parent=self.app):
            return
        del self.library[self.lib_sel]
        self.lib_sel = None
        self._persist()
        self._render_library()

    def _render_library(self):
        for w in self.lib_frame.winfo_children():
            w.destroy()
        if not self.library:
            label(self.lib_frame, "Nothing saved yet", 9, T.MUTED).pack(anchor="w", pady=px(4))
        for i, item in enumerate(self.library):
            sel = i == self.lib_sel
            bg = T.ACCENT_DIM if sel else T.SURFACE2
            row = tk.Frame(self.lib_frame, bg=bg, cursor="hand2", highlightthickness=1,
                           highlightbackground=T.ACCENT if sel else T.BORDER)
            row.pack(fill="x", pady=px(2))
            n = len(item["macro"].get("steps", []))
            a = label(row, item["name"], 10, T.ACCENT if sel else T.TEXT, True, bg=bg)
            a.pack(anchor="w", padx=px(10), pady=(px(6), 0))
            b = label(row, f"{n} step{'s' if n != 1 else ''}", 8, T.MUTED, bg=bg)
            b.pack(anchor="w", padx=px(10), pady=(0, px(6)))
            for w in (row, a, b):
                w.bind("<Button-1>", lambda e, i=i: self._pick(i))

    def _pick(self, i: int):
        if i == self.lib_sel:
            return
        if not self._confirm_discard():
            return
        item = self.library[i]
        self._load_macro(M.Macro.from_dict(item["macro"]), item["name"], i)

    def _render_mouse(self, snap: dict):
        for w in self.mouse_frame.winfo_children():
            w.destroy()
        found = False
        for name in K.BUTTONS:
            spec = snap["buttons"].get(name, {})
            fn = spec.get("function", "")
            if fn != "macro" and fn not in K.MACRO_ACTIONS:
                continue
            found = True
            row = tk.Frame(self.mouse_frame, bg=T.SURFACE)
            row.pack(fill="x", pady=px(3))
            txt = tk.Frame(row, bg=T.SURFACE)
            txt.pack(side="left")
            label(txt, BUTTON_TITLES[name], 10, T.TEXT, True).pack(anchor="w")
            from .labels import friendly
            label(txt, friendly(fn), 8, T.MUTED).pack(anchor="w")
            FlatButton(row, "Edit", lambda n=name, sp=spec: self._load_from_mouse(n, sp), "secondary", size=9,
                       padx=12, pady=4).pack(side="right")
        if not found:
            label(self.mouse_frame, "No button uses a macro", 9, T.MUTED).pack(anchor="w")

    def _load_from_mouse(self, name: str, spec: dict):
        if not self._confirm_discard():
            return
        if "macro" in spec:
            m = M.Macro.from_dict(spec["macro"])
        else:
            m, _ = M.preset(spec["function"], fire_interval=spec.get("fire_interval", 50))
        common = M.common_delay(m)
        if common is not None and m.fixed_delay is None:
            m.fixed_delay = common
        self._load_macro(m, f"{BUTTON_TITLES[name]} macro")
        self.target.set(name)
        self.modified = False

    def load(self, snap: dict):
        if not self.app_library_loaded:
            self.app_library_loaded = True
            if self._library_path_enabled():
                self.library = S.macro_library()
            self._render_library()
        self._render_mouse(snap)

    def on_show(self, target: str | None = None):
        if target in K.BUTTONS:
            self.target.set(target)
            spec = self.app.snap.get("buttons", {}).get(target) if self.app.snap else None
            if spec and (spec.get("function") == "macro" or spec.get("function") in K.MACRO_ACTIONS) \
                    and not self.modified:
                self._load_from_mouse(target, spec)

    # ------------------------------------------------------------------ record / assign
    def record(self):
        RecordDialog(self.app, self._recorded)

    def _recorded(self, events):
        steps = M.steps_from_events(events)
        self.macro.steps.extend(steps)
        self._mark()
        self.render_steps()
        self.app.toast.show(f"Recorded {len(steps)} steps", "ok", 2000)

    def assign(self):
        app = self.app
        if not app.dev:
            app.toast.show("No mouse connected", "error", 2500)
            return
        try:
            m = self._collect()
            if not m.steps:
                raise ValueError("The macro has no steps yet")
            M.encode(m)
        except ValueError as e:
            app.toast.show(str(e), "error", 3500)
            return
        name = self.target.get()
        idx = K.BUTTONS.index(name)
        dev = app.dev
        spec = {"function": "macro", "macro": m.to_dict()}

        def work():
            dev.set_button(idx, spec)
            return {"buttons": {name: dev.get_button(idx)}}

        def done(partial):
            from .app import _merge
            _merge(app.snap, partial)
            for p in app.pages.values():
                if not p.dirty:
                    p.reload()
            app.refresh_footer()
            app.toast.show("Nothing written (dry run)" if app.dry_run else
                           f"Macro assigned to {BUTTON_TITLES[name].lower()}", "ok", 2500)
        app.run_bg(work, done, "Writing macro…")
