"""Small custom widgets (Tkinter canvas / label based) that give the app a modern look."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable, Sequence

from . import theme as T
from .theme import px


def _bg_of(master) -> str:
    try:
        return master.cget("bg")
    except tk.TclError:
        return T.SURFACE


def watch(widget: tk.Misc, var: tk.Variable, callback: Callable[[], None]) -> None:
    """Call ``callback`` whenever ``var`` changes, for as long as ``widget`` exists.

    Variables outlive widgets (pages rebuild their option panels), so the trace is removed on destroy.
    """
    tid = var.trace_add("write", lambda *a: callback())

    def cleanup(e):
        if e.widget is widget:
            try:
                var.trace_remove("write", tid)
            except tk.TclError:
                pass
    widget.bind("<Destroy>", cleanup, add="+")


def label(master, text="", size=10, color=T.TEXT, bold=False, bg=None, **kw) -> tk.Label:
    return tk.Label(master, text=text, bg=bg or _bg_of(master), fg=color, font=T.font(size, bold),
                    bd=0, highlightthickness=0, **kw)


def hline(master, color=T.BORDER) -> tk.Frame:
    return tk.Frame(master, bg=color, height=1)


class Card(tk.Frame):
    """Bordered surface.  Put content into ``card.body``."""

    def __init__(self, master, title: str | None = None, subtitle: str | None = None, pad: int = 18,
                 bg: str = T.SURFACE, **kw):
        super().__init__(master, bg=bg, highlightthickness=1, highlightbackground=T.BORDER,
                         highlightcolor=T.BORDER, **kw)
        self.body = tk.Frame(self, bg=bg)
        self.body.pack(fill="both", expand=True, padx=px(pad), pady=px(pad))
        if title:
            label(self.body, title, 11, T.TEXT, True).pack(anchor="w")
        if subtitle:
            label(self.body, subtitle, 9, T.MUTED, wraplength=px(520), justify="left").pack(
                anchor="w", pady=(px(2), 0))
        if title or subtitle:
            tk.Frame(self.body, bg=bg, height=px(10)).pack()


class FlatButton(tk.Label):
    KINDS = {
        "primary": (T.ACCENT, T.ACCENT_HOVER, T.ACCENT_TEXT),
        "secondary": (T.SURFACE2, T.SURFACE3, T.TEXT),
        "ghost": (None, T.SURFACE2, T.MUTED),
        "danger": ("#3a1d1f", "#52282b", T.DANGER),
    }

    def __init__(self, master, text: str, command: Callable | None = None, kind: str = "secondary",
                 width: int | None = None, size: int = 10, padx: int = 16, pady: int = 8):
        self.kind = kind
        bg, self._hover, fg = self.KINDS[kind]
        self._bg = bg or _bg_of(master)
        self._fg = fg
        super().__init__(master, text=text, bg=self._bg, fg=fg, font=T.font(size, True), bd=0,
                         padx=px(padx), pady=px(pady), cursor="hand2", width=width or 0)
        self._cmd = command
        self._enabled = True
        self._down = False
        self.bind("<Enter>", lambda e: self._enabled and self.configure(bg=self._hover))
        self.bind("<Leave>", lambda e: self.configure(bg=self._bg))
        self.bind("<ButtonPress-1>", self._press)
        self.bind("<ButtonRelease-1>", self._release)

    def _press(self, _e):
        self._down = True

    def _release(self, e):
        inside = 0 <= e.x < self.winfo_width() and 0 <= e.y < self.winfo_height()
        if self._down and inside and self._enabled and self._cmd:
            self._cmd()
        self._down = False

    def set_enabled(self, on: bool) -> None:
        self._enabled = on
        self.configure(fg=self._fg if on else T.FAINT, cursor="hand2" if on else "arrow",
                       bg=self._bg)

    def set_text(self, text: str) -> None:
        self.configure(text=text)


class Toggle(tk.Canvas):
    """iOS style switch bound to a BooleanVar."""

    def __init__(self, master, variable: tk.BooleanVar, command: Callable | None = None):
        self.w, self.h = px(40), px(22)
        super().__init__(master, width=self.w, height=self.h, bg=_bg_of(master), bd=0,
                         highlightthickness=0, cursor="hand2")
        self.var, self.cmd, self.enabled = variable, command, True
        watch(self, self.var, self._draw)
        self.bind("<Button-1>", self._click)
        self._draw()

    def _click(self, _e):
        if self.enabled:
            self.var.set(not self.var.get())
            if self.cmd:
                self.cmd()

    def set_enabled(self, on: bool) -> None:
        self.enabled = on
        self.configure(cursor="hand2" if on else "arrow")
        self._draw()

    def _draw(self):
        self.delete("all")
        on = bool(self.var.get())
        track = T.ACCENT if on else T.SURFACE3
        if not self.enabled:
            track = T.mix(track, T.BG, 0.55)
        h, w = self.h, self.w
        self.create_oval(1, 1, h - 1, h - 1, fill=track, outline=track)
        self.create_oval(w - h + 1, 1, w - 1, h - 1, fill=track, outline=track)
        self.create_rectangle(h // 2, 1, w - h // 2, h - 1, fill=track, outline=track)
        r = h // 2 - px(3)
        cx = w - h // 2 if on else h // 2
        self.create_oval(cx - r, h // 2 - r, cx + r, h // 2 + r, fill="#ffffff" if self.enabled else T.MUTED,
                         outline="")


class Slider(tk.Canvas):
    """Horizontal slider over an integer range, bound to an IntVar."""

    def __init__(self, master, variable: tk.IntVar, from_: int, to: int, width: int = 260,
                 command: Callable | None = None, step: int = 1, curve: float = 1.0):
        self.w, self.h = px(width), px(26)
        super().__init__(master, width=self.w, height=self.h, bg=_bg_of(master), bd=0,
                         highlightthickness=0, cursor="hand2", takefocus=1)
        self.var, self.lo, self.hi, self.cmd, self.step = variable, from_, to, command, step
        self.curve = curve          # <1 gives the low end of the range more room (position = frac ** curve)
        self.enabled = True
        watch(self, self.var, self._draw)
        self.bind("<Button-1>", self._set_from_event)
        self.bind("<B1-Motion>", self._set_from_event)
        self.bind("<MouseWheel>", self._wheel)
        self.bind("<Left>", lambda e: self._nudge(-self.step))
        self.bind("<Right>", lambda e: self._nudge(self.step))
        self._draw()

    def configure_range(self, lo: int, hi: int) -> None:
        self.lo, self.hi = lo, hi
        self._draw()

    def _wheel(self, e):
        """The wheel changes the value only after the slider was clicked; otherwise the page scrolls."""
        if self.enabled and self.focus_get() is self:
            self._nudge(self.step if e.delta > 0 else -self.step)
            return "break"
        return None

    def set_enabled(self, on: bool) -> None:
        self.enabled = on
        self._draw()

    def _frac(self) -> float:
        span = max(1, self.hi - self.lo)
        return min(1.0, max(0.0, (self.var.get() - self.lo) / span)) ** self.curve

    def _set_from_event(self, e):
        if not self.enabled:
            return
        self.focus_set()
        pad = px(10)
        frac = min(1.0, max(0.0, (e.x - pad) / max(1, self.w - 2 * pad))) ** (1.0 / self.curve)
        v = self.lo + round((frac * (self.hi - self.lo)) / self.step) * self.step
        self._commit(int(min(self.hi, max(self.lo, v))))

    def _nudge(self, d: int):
        if self.enabled:
            self._commit(int(min(self.hi, max(self.lo, self.var.get() + d))))

    def _commit(self, v: int):
        if v != self.var.get():
            self.var.set(v)
            if self.cmd:
                self.cmd()

    def _draw(self):
        self.delete("all")
        pad, y = px(10), self.h // 2
        x1 = pad + self._frac() * (self.w - 2 * pad)
        tr = px(3)
        fill = T.ACCENT if self.enabled else T.FAINT
        self.create_line(pad, y, self.w - pad, y, fill=T.SURFACE3, width=tr * 2 - 1, capstyle="round")
        if x1 > pad:
            self.create_line(pad, y, x1, y, fill=fill, width=tr * 2 - 1, capstyle="round")
        r = px(8)
        self.create_oval(x1 - r, y - r, x1 + r, y + r, fill="#ffffff" if self.enabled else T.MUTED,
                         outline=fill, width=px(2))


class Segmented(tk.Frame):
    """Pill-shaped option selector bound to a variable holding the option value."""

    def __init__(self, master, options: Sequence[tuple], variable: tk.Variable,
                 command: Callable | None = None, size: int = 10, padx: int = 14, pady: int = 6):
        super().__init__(master, bg=T.SURFACE2, highlightthickness=1, highlightbackground=T.BORDER)
        self.var, self.cmd, self.items, self.enabled = variable, command, {}, True
        for value, text in options:
            lb = tk.Label(self, text=text, font=T.font(size, True), padx=px(padx), pady=px(pady), bd=0,
                          cursor="hand2", bg=T.SURFACE2, fg=T.MUTED)
            lb.pack(side="left", padx=px(2), pady=px(2))
            lb.bind("<Button-1>", lambda e, v=value: self._pick(v))
            self.items[value] = lb
        watch(self, self.var, self._refresh)
        self._refresh()

    def _pick(self, value):
        if not self.enabled:
            return
        self.var.set(value)
        if self.cmd:
            self.cmd()

    def set_enabled(self, on: bool) -> None:
        self.enabled = on
        self._refresh()

    def _refresh(self):
        cur = self.var.get()
        for value, lb in self.items.items():
            sel = str(value) == str(cur)
            if sel:
                lb.configure(bg=T.ACCENT if self.enabled else T.FAINT, fg="#ffffff")
            else:
                lb.configure(bg=T.SURFACE2, fg=T.MUTED if self.enabled else T.FAINT)


class Chip(tk.Label):
    def __init__(self, master, text: str, on_click: Callable[[], None]):
        super().__init__(master, text=text, font=T.font(10), padx=px(12), pady=px(7), bd=0, cursor="hand2",
                         bg=T.SURFACE2, fg=T.TEXT, highlightthickness=1, highlightbackground=T.BORDER)
        self.selected = False
        self.bind("<Button-1>", lambda e: on_click())
        self.bind("<Enter>", lambda e: self._paint(hover=True))
        self.bind("<Leave>", lambda e: self._paint())

    def set_selected(self, on: bool) -> None:
        self.selected = on
        self._paint()

    def _paint(self, hover: bool = False):
        if self.selected:
            self.configure(bg=T.ACCENT_DIM, fg=T.ACCENT, highlightbackground=T.ACCENT)
        else:
            self.configure(bg=T.SURFACE3 if hover else T.SURFACE2, fg=T.TEXT, highlightbackground=T.BORDER)


class ChipGrid(tk.Frame):
    """Wrapping grid of selectable chips; selection stored as the chip value."""

    def __init__(self, master, items: Sequence[tuple[str, str]], variable: tk.StringVar,
                 command: Callable[[str], None] | None = None, columns: int = 4):
        super().__init__(master, bg=_bg_of(master))
        self.var, self.cmd, self.chips = variable, command, {}
        for i, (value, text) in enumerate(items):
            chip = Chip(self, text, lambda v=value: self._pick(v))
            chip.grid(row=i // columns, column=i % columns, padx=px(3), pady=px(3), sticky="ew")
            self.chips[value] = chip
        for c in range(columns):
            self.columnconfigure(c, weight=1, uniform="chip")
        watch(self, self.var, self.refresh)
        self.refresh()

    def _pick(self, value):
        self.var.set(value)
        if self.cmd:
            self.cmd(value)

    def refresh(self):
        cur = self.var.get()
        for v, c in self.chips.items():
            c.set_selected(v == cur)


class ColorDot(tk.Canvas):
    """Round colour swatch; clicking it runs ``command``."""

    def __init__(self, master, color: str = "#ffffff", size: int = 30, command: Callable | None = None):
        s = px(size)
        super().__init__(master, width=s, height=s, bg=_bg_of(master), bd=0, highlightthickness=0,
                         cursor="hand2")
        self.size, self.cmd, self.color, self.dim = s, command, color, False
        self.bind("<Button-1>", lambda e: self.cmd and self.cmd())
        self.set(color)

    def set(self, color: str, dim: bool = False) -> None:
        self.color, self.dim = color, dim
        self.delete("all")
        s = self.size
        shown = T.mix(color, T.BG, 0.65) if dim else color
        self.create_oval(2, 2, s - 2, s - 2, fill=shown, outline=T.BORDER if dim else T.mix(color, "#ffffff", 0.35),
                         width=px(2))


class ScrollFrame(tk.Frame):
    """Vertically scrolling container; add content to ``.inner``."""

    def __init__(self, master, bg: str = T.BG):
        super().__init__(master, bg=bg)
        self.canvas = tk.Canvas(self, bg=bg, bd=0, highlightthickness=0, yscrollincrement=px(30))
        self.bar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview, style="Slim.Vertical.TScrollbar")
        self.canvas.configure(yscrollcommand=self._on_scroll)
        self.inner = tk.Frame(self.canvas, bg=bg)
        self._win = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.inner.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(self._win, width=e.width))

    def _on_scroll(self, lo, hi):
        self.bar.set(lo, hi)
        if float(lo) <= 0.0 and float(hi) >= 1.0:
            self.bar.pack_forget()
        elif not self.bar.winfo_ismapped():
            self.bar.pack(side="right", fill="y")

    # -- wheel support ----------------------------------------------------------------
    def scroll_by(self, notches: float) -> bool:
        """Scroll by mouse-wheel notches (positive = down).  False if there is nothing to scroll."""
        lo, hi = self.canvas.yview()
        if lo <= 0.0 and hi >= 1.0:
            return False
        self.canvas.yview_scroll(int(round(notches * 3)) or (1 if notches > 0 else -1), "units")
        return True

    @staticmethod
    def owner_of(widget) -> "ScrollFrame | None":
        """The ScrollFrame that contains ``widget`` (walking up the widget tree), if any."""
        while widget is not None:
            if isinstance(widget, ScrollFrame):
                return widget
            widget = getattr(widget, "master", None)
        return None


def install_wheel(root: tk.Misc) -> None:
    """One application-wide mouse-wheel handler: scroll the scroll area under the pointer.

    (Per-widget Enter/Leave bindings do not work: entering a child widget fires <Leave> on its parent.)
    """
    def on_wheel(event):
        try:
            under = root.winfo_containing(event.x_root, event.y_root)
        except (tk.TclError, KeyError):
            return None
        if under is None or isinstance(under, (tk.Text, tk.Listbox, tk.Spinbox)):
            return None                         # those scroll themselves
        sf = ScrollFrame.owner_of(under)
        if sf is not None and sf.scroll_by(-event.delta / 120.0):
            return "break"
        return None

    root.bind_all("<MouseWheel>", on_wheel, add="+")


class Toast(tk.Frame):
    """Transient message in the bottom-right corner."""

    COLORS = {"info": (T.SURFACE2, T.TEXT, T.BORDER), "ok": ("#10281f", T.OK, "#1f5a43"),
              "error": ("#2d1517", T.DANGER, "#6b2b2f")}

    def __init__(self, master):
        super().__init__(master, bd=0)
        self.lb = tk.Label(self, font=T.font(10), padx=px(16), pady=px(10), justify="left", wraplength=px(420))
        self.lb.pack()
        self._after = None
        self.master = master

    def cancel(self) -> None:
        if self._after:
            try:
                self.after_cancel(self._after)
            except tk.TclError:
                pass
            self._after = None

    def show(self, text: str, kind: str = "info", ms: int = 3500) -> None:
        bg, fg, border = self.COLORS[kind]
        self.configure(bg=border, padx=1, pady=1)
        self.lb.configure(text=text, bg=bg, fg=fg)
        footer = getattr(self.master, "footer", None)
        lift = footer.winfo_height() + px(16) if footer is not None and footer.winfo_ismapped() else px(28)
        self.place(relx=1.0, rely=1.0, x=-px(24), y=-lift, anchor="se")
        self.lift()
        if self._after:
            self.after_cancel(self._after)
        self._after = self.after(ms if kind != "error" else max(ms, 7000), self.place_forget)


def style_ttk(root) -> None:
    st = ttk.Style(root)
    st.theme_use("clam")
    st.configure("Slim.Vertical.TScrollbar", troughcolor=T.BG, background=T.SURFACE3, bordercolor=T.BG,
                 lightcolor=T.SURFACE3, darkcolor=T.SURFACE3, arrowsize=px(13), gripcount=0, relief="flat")
    st.map("Slim.Vertical.TScrollbar", background=[("active", T.FAINT)])
