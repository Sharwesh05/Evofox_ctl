"""Main window: sidebar navigation, header, apply bar, background jobs, auto refresh."""

from __future__ import annotations

import ctypes
import queue
import sys
import threading
import time
import tkinter as tk
from tkinter import messagebox

from .. import protocol as P
from .. import settings as S
from ..devices import DeviceEntry, MockSource, RealSource, pick
from ..device import GhostX, capabilities
from . import theme as T
from .theme import px
from .widgets import FlatButton, ScrollFrame, Segmented, Toast, Toggle, hline, install_wheel, label, style_ttk
from .pages import PAGES

NAV_ICONS = {"overview": "⌂", "buttons": "◉", "macros": "▶", "dpi": "◎", "performance": "⚡",
             "backup": "⇅", "log": "☰"}


def _enable_dpi_awareness() -> None:
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:  # noqa: BLE001
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:  # noqa: BLE001
            pass


def _make_icon(size: int = 32) -> tk.PhotoImage:
    img = tk.PhotoImage(width=size, height=size)
    r, c = size * 0.22, size / 2
    for y in range(size):
        row = []
        for x in range(size):
            dx, dy = abs(x + 0.5 - c) - (c - r), abs(y + 0.5 - c) - (c - r)
            inside = (max(dx, 0) ** 2 + max(dy, 0) ** 2) ** 0.5 <= r
            col = "#ff5a1f" if inside else None
            if inside:
                ex, ey = (x + 0.5 - c) / (size * 0.20), (y + 0.5 - c * 1.06) / (size * 0.32)
                if ex * ex + ey * ey <= 1:
                    col = "#ffffff"
                    if abs(x + 0.5 - c) < size * 0.025 and y < size * 0.5:
                        col = "#ff5a1f"
                    if y + 0.5 < c * 0.92 and abs(x + 0.5 - c) < size * 0.035:
                        col = "#ff5a1f"
            row.append(col or "{}")
        img.put("{" + " ".join(c if c != "{}" else "#000000" for c in row) + "}", to=(0, y))
    # make the area outside the rounded square transparent
    for y in range(size):
        for x in range(size):
            dx, dy = abs(x + 0.5 - c) - (c - r), abs(y + 0.5 - c) - (c - r)
            if (max(dx, 0) ** 2 + max(dy, 0) ** 2) ** 0.5 > r:
                img.transparency_set(x, y, True)
    return img


class App(tk.Tk):
    def __init__(self, mock: bool = False, dry_run: bool = False, device: int | None = None):
        super().__init__()
        self._start_index = device       # `ghostx --device N gui`: used for the first connection only
        scale = max(1.0, self.winfo_fpixels("1i") / 96.0)
        T.set_scale(scale)
        self.mock, self.dry_run = mock, dry_run
        self.source = MockSource() if mock else RealSource()
        self.entries: list[DeviceEntry] = []
        self.entry: DeviceEntry | None = None
        self._sig: tuple | None = None
        self.prefs = {} if mock else S.load()
        self.dev: GhostX | None = None
        self.snap: dict = {}
        self.status = None
        self.caps = capabilities(0)
        self.jobs: queue.Queue = queue.Queue()
        self.busy = self.busy_quiet = False
        self.log_lines: list[str] = []
        self.log_q: queue.SimpleQueue = queue.SimpleQueue()   # filled by worker threads, drained in _pump
        self._auto_after = None
        self.pages: dict[str, object] = {}
        self.page_frames: dict[str, ScrollFrame] = {}
        self.current = None

        self.title("EvoFox Ghost X")
        try:
            self.iconphoto(True, _make_icon())
        except tk.TclError:
            pass
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        w, h = min(px(1220), int(sw * 0.92)), min(px(800), int(sh * 0.9))
        self.geometry(f"{w}x{h}+{(sw - w) // 2}+{max(0, (sh - h) // 3)}")
        self.minsize(min(px(1020), w), min(px(660), h))
        self.configure(bg=T.BG)
        style_ttk(self)
        install_wheel(self)
        self.option_add("*TCombobox*Listbox.font", T.font(10))

        self._build()
        self.toast = Toast(self)
        self._pump_after = self.after(100, self._pump)
        self.protocol("WM_DELETE_WINDOW", self._close)
        self.after(30, self._dark_titlebar)
        self.after(150, self.connect)
        self._schedule_auto()

    def _dark_titlebar(self) -> None:
        """Windows 10/11: dark caption bar matching the app background."""
        if sys.platform != "win32":
            return
        try:
            hwnd = ctypes.windll.user32.GetParent(self.winfo_id())
            dwm = ctypes.windll.dwmapi
            one = ctypes.c_int(1)
            dwm.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(one), 4)       # immersive dark mode
            rgb = int(T.BG[1:], 16)
            bgr = ctypes.c_int(((rgb & 0xFF) << 16) | (rgb & 0xFF00) | (rgb >> 16))
            dwm.DwmSetWindowAttribute(hwnd, 35, ctypes.byref(bgr), 4)       # caption colour (Win 11)
            txt = ctypes.c_int(int(T.TEXT[1:3], 16) | (int(T.TEXT[3:5], 16) << 8) | (int(T.TEXT[5:7], 16) << 16))
            dwm.DwmSetWindowAttribute(hwnd, 36, ctypes.byref(txt), 4)       # caption text colour
        except Exception:  # noqa: BLE001 - cosmetic only
            pass

    # ------------------------------------------------------------------ layout
    def _build(self) -> None:
        self.sidebar = tk.Frame(self, bg=T.SIDEBAR, width=px(232))
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)
        tk.Frame(self, bg=T.BORDER, width=1).pack(side="left", fill="y")
        self.main = tk.Frame(self, bg=T.BG)
        self.main.pack(side="left", fill="both", expand=True)
        self._build_sidebar()
        self._build_main()

    def _build_sidebar(self) -> None:
        sb = self.sidebar
        brand = tk.Frame(sb, bg=T.SIDEBAR)
        brand.pack(fill="x", padx=px(22), pady=(px(26), px(18)))
        label(brand, "GHOST X", 16, T.TEXT, True, bg=T.SIDEBAR).pack(anchor="w")
        label(brand, "EvoFox configurator", 9, T.MUTED, bg=T.SIDEBAR).pack(anchor="w")

        card = tk.Frame(sb, bg=T.SURFACE, highlightthickness=1, highlightbackground=T.BORDER)
        card.pack(fill="x", padx=px(16), pady=(0, px(18)))
        inner = tk.Frame(card, bg=T.SURFACE)
        inner.pack(fill="x", padx=px(14), pady=px(12))
        self.picker = tk.Frame(inner, bg=T.SURFACE, cursor="hand2")
        self.picker.pack(fill="x", pady=(0, px(8)))
        self.picker_name = tk.StringVar(value="No mouse")
        self.picker_lbl = tk.Label(self.picker, textvariable=self.picker_name, bg=T.SURFACE, fg=T.TEXT,
                                   font=T.font(10, True), anchor="w", cursor="hand2")
        self.picker_lbl.pack(side="left")
        self.picker_arrow = tk.Label(self.picker, text="\u25be", bg=T.SURFACE, fg=T.MUTED, font=T.font(10),
                                     cursor="hand2")
        self.picker_arrow.pack(side="right")
        for w in (self.picker, self.picker_lbl, self.picker_arrow):
            w.bind("<Button-1>", self._open_device_menu)
        hline(inner).pack(fill="x", pady=(0, px(8)))
        row = tk.Frame(inner, bg=T.SURFACE)
        row.pack(fill="x")
        self.dot = tk.Canvas(row, width=px(10), height=px(10), bg=T.SURFACE, highlightthickness=0, bd=0)
        self.dot.pack(side="left")
        self.dot_item = self.dot.create_oval(1, 1, px(9), px(9), fill=T.FAINT, outline="")
        self.conn_var = tk.StringVar(value="Connecting…")
        tk.Label(row, textvariable=self.conn_var, bg=T.SURFACE, fg=T.TEXT, font=T.font(10, True)).pack(
            side="left", padx=(px(8), 0))
        self.sub_var = tk.StringVar(value="")
        tk.Label(inner, textvariable=self.sub_var, bg=T.SURFACE, fg=T.MUTED, font=T.font(9),
                 anchor="w").pack(fill="x", pady=(px(2), px(8)))
        self.bat = tk.Canvas(inner, height=px(8), bg=T.SURFACE, highlightthickness=0, bd=0)
        self.bat.pack(fill="x")
        self.bat.bind("<Configure>", lambda e: self._draw_battery())
        self.bat_var = tk.StringVar(value="")
        tk.Label(inner, textvariable=self.bat_var, bg=T.SURFACE, fg=T.MUTED, font=T.font(9), anchor="w").pack(
            fill="x", pady=(px(6), 0))

        self.nav_items: dict[str, tk.Frame] = {}
        for key, cls in PAGES.items():
            item = tk.Frame(sb, bg=T.SIDEBAR, cursor="hand2")
            item.pack(fill="x", padx=px(10), pady=px(1))
            bar = tk.Frame(item, bg=T.SIDEBAR, width=px(3))
            bar.pack(side="left", fill="y")
            icon = tk.Label(item, text=NAV_ICONS.get(key, "•"), bg=T.SIDEBAR, fg=T.MUTED,
                            font=("Segoe UI Symbol", 11), width=2)
            icon.pack(side="left", padx=(px(10), 0), pady=px(9))
            txt = tk.Label(item, text=cls.title, bg=T.SIDEBAR, fg=T.MUTED, font=T.font(10, True), anchor="w")
            txt.pack(side="left", fill="x", expand=True, padx=(px(4), 0))
            item.parts = (bar, icon, txt)
            for w in (item, icon, txt):
                w.bind("<Button-1>", lambda e, k=key: self.show_page(k))
                w.bind("<Enter>", lambda e, k=key: self._nav_paint(k, hover=True))
                w.bind("<Leave>", lambda e, k=key: self._nav_paint(k))
            self.nav_items[key] = item

        bottom = tk.Frame(sb, bg=T.SIDEBAR)
        bottom.pack(side="bottom", fill="x", padx=px(18), pady=px(18))
        row = tk.Frame(bottom, bg=T.SIDEBAR)
        row.pack(fill="x")
        label(row, "Auto refresh", 10, T.TEXT, True, bg=T.SIDEBAR).pack(side="left")
        self.auto_var = tk.BooleanVar(value=self.prefs.get("auto_refresh", True))
        Toggle(row, self.auto_var, command=self._on_auto_toggle).pack(side="right")
        self.auto_secs = tk.StringVar(value=str(self.prefs.get("auto_secs", 10)))
        step = tk.Frame(bottom, bg=T.SIDEBAR)
        step.pack(anchor="w", pady=(px(8), px(4)))
        FlatButton(step, "−", lambda: self._step_interval(-1), "secondary", size=10, padx=10, pady=3).pack(side="left")
        field = tk.Frame(step, bg=T.SURFACE2, highlightthickness=1, highlightbackground=T.BORDER)
        field.pack(side="left", padx=px(4))
        self.secs_entry = tk.Entry(field, textvariable=self.auto_secs, width=4, justify="center", bg=T.SURFACE2,
                                   fg=T.TEXT, insertbackground=T.TEXT, relief="flat", bd=0, font=T.font(10, True),
                                   highlightthickness=0)
        self.secs_entry.pack(side="left", padx=(px(4), 0), pady=px(4))
        label(field, "sec", 9, T.MUTED, bg=T.SURFACE2).pack(side="left", padx=(px(2), px(6)))
        FlatButton(step, "+", lambda: self._step_interval(1), "secondary", size=10, padx=10, pady=3).pack(side="left")
        self.secs_entry.bind("<Return>", lambda e: (self._commit_interval(), self.focus_set()))
        self.secs_entry.bind("<FocusOut>", lambda e: self._commit_interval())
        self.refresh_var = tk.StringVar(value="")
        tk.Label(bottom, textvariable=self.refresh_var, bg=T.SIDEBAR, fg=T.FAINT, font=T.font(8),
                 anchor="w", wraplength=px(190), justify="left").pack(fill="x")

    def _build_main(self) -> None:
        banner_text = None
        if self.mock:
            banner_text = "SIMULATED MOUSE — no hardware is used"
        elif self.dry_run:
            banner_text = "DRY RUN — settings are read from the mouse but nothing is written"
        if banner_text:
            b = tk.Label(self.main, text=banner_text, bg="#3a2e10", fg=T.WARN, font=T.font(9, True), pady=px(5))
            b.pack(fill="x")

        head = tk.Frame(self.main, bg=T.BG)
        head.pack(fill="x", padx=px(30), pady=(px(22), px(8)))
        titles = tk.Frame(head, bg=T.BG)
        titles.pack(side="left")
        self.title_var, self.subtitle_var = tk.StringVar(), tk.StringVar()
        tk.Label(titles, textvariable=self.title_var, bg=T.BG, fg=T.TEXT, font=T.font(20, True),
                 anchor="w").pack(anchor="w")
        tk.Label(titles, textvariable=self.subtitle_var, bg=T.BG, fg=T.MUTED, font=T.font(10),
                 anchor="w").pack(anchor="w")
        right = tk.Frame(head, bg=T.BG)
        right.pack(side="right")
        FlatButton(right, "↻  Read from mouse", self.read_all, "ghost", size=9).pack(side="right", padx=(px(10), 0))
        self.profile_var = tk.IntVar(value=1)
        self.profile_seg = Segmented(right, [(n, f"Profile {n}") for n in range(1, P.PROFILE_COUNT + 1)],
                                     self.profile_var, command=self.switch_profile, size=9, padx=12, pady=5)
        self.profile_seg.pack(side="right")

        # footer (apply bar) is packed before the content so it stays visible
        self.footer = tk.Frame(self.main, bg=T.SURFACE, highlightthickness=1, highlightbackground=T.BORDER)
        fin = tk.Frame(self.footer, bg=T.SURFACE)
        fin.pack(fill="x", padx=px(30), pady=px(12))
        tk.Label(fin, text="●", fg=T.ACCENT, bg=T.SURFACE, font=T.font(10)).pack(side="left")
        self.footer_var = tk.StringVar()
        tk.Label(fin, textvariable=self.footer_var, bg=T.SURFACE, fg=T.TEXT, font=T.font(10)).pack(
            side="left", padx=(px(8), 0))
        self.apply_btn = FlatButton(fin, "Apply to mouse", self.apply_current, "primary")
        self.apply_btn.pack(side="right")
        FlatButton(fin, "Discard", self.discard_current, "ghost").pack(side="right", padx=(0, px(8)))

        self.content = tk.Frame(self.main, bg=T.BG)
        self.content.pack(fill="both", expand=True)
        for key, cls in PAGES.items():
            sf = ScrollFrame(self.content)
            self.page_frames[key] = sf
            sf.inner.configure(padx=px(30), pady=px(8))
            page = cls(self, sf.inner)
            page.frame.pack(fill="both", expand=True)
            self.pages[key] = page

        # empty state shown while there is no device
        self.empty = tk.Frame(self.content, bg=T.BG)
        box = tk.Frame(self.empty, bg=T.BG)
        box.place(relx=0.5, rely=0.42, anchor="center")
        self.empty_title = tk.Label(box, text="Looking for your mouse…", bg=T.BG, fg=T.TEXT, font=T.font(16, True))
        self.empty_title.pack()
        self.empty_text = tk.Label(box, text="", bg=T.BG, fg=T.MUTED, font=T.font(10), justify="center",
                                   wraplength=px(460))
        self.empty_text.pack(pady=(px(6), px(16)))
        self.empty_btn = FlatButton(box, "Try again", self.connect, "primary")
        self.empty_btn.pack()
        self.empty.place(relx=0, rely=0, relwidth=1, relheight=1)
        self.show_page("overview")

    # ------------------------------------------------------------------ navigation
    def _nav_paint(self, key: str, hover: bool = False) -> None:
        item = self.nav_items[key]
        bar, icon, txt = item.parts
        active = key == self.current
        bg = T.SURFACE2 if active else (T.SURFACE if hover else T.SIDEBAR)
        item.configure(bg=bg)
        bar.configure(bg=T.ACCENT if active else bg)
        icon.configure(bg=bg, fg=T.ACCENT if active else T.MUTED)
        txt.configure(bg=bg, fg=T.TEXT if active else T.MUTED)

    def show_page(self, key: str, **kw) -> None:
        if self.current:
            self.page_frames[self.current].pack_forget()
        self.current = key
        page = self.pages[key]
        self.page_frames[key].pack(fill="both", expand=True)
        for k in self.nav_items:
            self._nav_paint(k)
        self.title_var.set(page.title)
        self.subtitle_var.set(page.subtitle)
        if hasattr(page, "on_show"):
            page.on_show(**kw)
        self.refresh_footer()

    def refresh_footer(self) -> None:
        page = self.pages.get(self.current)
        if page is not None and page.dirty:
            self.footer_var.set(page.dirty_text())
            self.footer.pack(side="bottom", fill="x", before=self.content)
        else:
            self.footer.pack_forget()

    # ------------------------------------------------------------------ jobs
    def run_bg(self, fn, done=None, what: str = "", quiet: bool = False) -> None:
        if self.busy:
            if quiet:
                return
            if self.busy_quiet:
                self.after(300, lambda: self.run_bg(fn, done, what))
            else:
                self.toast.show("Still working on the previous request…", "info", 1500)
            return
        self.busy, self.busy_quiet = True, quiet
        if what:
            self.refresh_var.set(what)

        def work():
            try:
                self.jobs.put((done, fn(), None, quiet))
            except Exception as e:  # noqa: BLE001 - reported to the user
                self.jobs.put((done, None, e, quiet))

        threading.Thread(target=work, daemon=True).start()

    def _pump(self) -> None:
        while not self.log_q.empty():
            line = self.log_q.get()
            self.log_lines.append(line)
            del self.log_lines[:-2000]
            self.pages["log"].append(line)
        try:
            while True:
                done, res, err, quiet = self.jobs.get_nowait()
                self.busy = self.busy_quiet = False
                if err is not None:
                    if quiet:
                        self.refresh_var.set(f"Refresh failed {time.strftime('%H:%M:%S')}")
                        self.dot.itemconfigure(self.dot_item, fill=T.WARN)
                        self.conn_var.set("Not responding")
                    else:
                        self.toast.show(str(err), "error")
                        self.refresh_var.set("")
                        if self.dev is None:
                            self._show_empty("Couldn't connect" if self.entries else "No mouse found", str(err))
                            self._update_picker()
                else:
                    if done:
                        done(res)
        except queue.Empty:
            pass
        self._pump_after = self.after(100, self._pump)

    def log(self, text: str) -> None:
        self.log_q.put(f"{time.strftime('%H:%M:%S')}  {text}")   # thread-safe; shown by _pump

    # ------------------------------------------------------------------ connection / data
    def _show_empty(self, title: str, text: str) -> None:
        self.empty_title.configure(text=title)
        self.empty_text.configure(text=text)
        self.empty.place(relx=0, rely=0, relwidth=1, relheight=1)
        self.empty.lift()
        self.footer.pack_forget()
        self.dot.itemconfigure(self.dot_item, fill=T.DANGER)
        self.conn_var.set("Disconnected")
        self.sub_var.set("")
        self.bat_var.set("")
        self.bat.delete("all")

    def _drop_device(self) -> None:
        if self.dev:
            try:
                self.dev.close()
            except Exception:  # noqa: BLE001
                pass
            self.dev = None

    def connect(self, entry: DeviceEntry | None = None) -> None:
        """(Re)connect.  Without an argument the previously used mouse is preferred."""
        prefer = entry.key if entry else (self.entry.key if self.entry else self.prefs.get("last_device"))
        self._drop_device()
        self.empty_title.configure(text="Looking for your mouse\u2026")
        self.empty_text.configure(text="Plug in the mouse (or the 2.4 GHz dongle) and wake it with a click.")
        self.dot.itemconfigure(self.dot_item, fill=T.WARN)
        self.conn_var.set("Connecting\u2026")

        def work():
            entries = self.source.scan()
            self.entries = entries
            start, self._start_index = self._start_index, None
            chosen = pick(entries, index=start) if start is not None else pick(entries, key=prefer)
            sleep = (lambda s: None) if self.mock else time.sleep
            tag = chosen.label
            log = (lambda t: self.log(f"[{tag}] {t}")) if len(entries) > 1 else self.log
            dev = GhostX(chosen.open(), dry_run=self.dry_run, log=log, sleep=sleep)
            return entries, self.source.signature(), chosen, dev, dev.snapshot()

        def done(res):
            entries, sig, chosen, dev, snap = res
            self.entries, self._sig, self.entry, self.dev = entries, sig, chosen, dev
            self.fill(snap)
            self._update_picker()
            if not self.mock:
                S.save(last_device=chosen.key)
            self.toast.show(f"Connected to {chosen.label}", "ok", 2000)

        self.run_bg(work, done, "Reading settings\u2026")

    # ------------------------------------------------------------------ several mice
    def _update_picker(self) -> None:
        n = len(self.entries)
        if self.entry and self.dev:
            self.picker_name.set(self.entry.label)
        else:
            self.picker_name.set("No mouse found" if not n else "Select a mouse")
        self._show_status()

    def _open_device_menu(self, event=None) -> None:
        menu = tk.Menu(self, tearoff=0, bg=T.SURFACE2, fg=T.TEXT, activebackground=T.ACCENT,
                       activeforeground="#ffffff", bd=0, relief="flat", font=T.font(10), activeborderwidth=0)
        cur = self.entry.key if (self.entry and self.dev) else None
        if not self.entries:
            menu.add_command(label="No mouse found", state="disabled")
        for e in self.entries:
            menu.add_command(label=("\u25cf  " if e.key == cur else "     ") + e.label,
                             command=lambda e=e: self.select_device(e))
        menu.add_separator()
        menu.add_command(label="\u21bb  Rescan devices", command=self.rescan)
        x, y = self.picker.winfo_rootx(), self.picker.winfo_rooty() + self.picker.winfo_height()
        try:
            menu.tk_popup(x, y)
        finally:
            menu.grab_release()

    def select_device(self, entry: DeviceEntry) -> None:
        if self.entry and self.dev and entry.key == self.entry.key:
            return
        if self._any_dirty() and not messagebox.askyesno(
                "Unsaved changes", "Switching mouse will discard your unsaved changes. Continue?"):
            return
        self.connect(entry)

    def rescan(self) -> None:
        def work():
            return self.source.scan(), self.source.signature()

        def done(res):
            self._apply_scan(*res, announce=True)
        self.run_bg(work, done, "Scanning for mice\u2026")

    def _apply_scan(self, entries: list[DeviceEntry], sig: tuple, announce: bool = False) -> None:
        old = {e.key for e in self.entries}
        self.entries, self._sig = entries, sig
        new = [e for e in entries if e.key not in old]
        self._update_picker()
        cur = self.entry.key if self.entry else None
        if self.dev is not None and cur and not any(e.key == cur for e in entries):
            self._lost_device()
        elif announce:
            n = len(entries)
            self.toast.show(f"{n} mouse found" if n == 1 else (f"{n} mice found" if n else "No mouse found"),
                            "ok" if n else "error", 2500)
        elif new and old:
            self.toast.show(f"New mouse detected: {new[0].label} \u2014 switch from the device menu", "info", 4500)
        if self.dev is None and entries and not self._any_dirty():
            self.connect()

    def _lost_device(self) -> None:
        label_ = self.entry.label if self.entry else "The mouse"
        self._drop_device()
        for p in self.pages.values():
            p.dirty = False
        self._update_picker()
        if self.entries:                      # another mouse is still attached: carry on with it
            self.toast.show(f"{label_} disconnected — switching to {self.entries[0].label}", "info", 4500)
            return
        self._show_empty(f"{label_} was disconnected",
                         "Plug the mouse or its 2.4 GHz dongle back in — it will reconnect automatically.")
        self.toast.show(f"{label_} disconnected", "error", 4000)

    def read_all(self) -> None:
        if not self.dev:
            return self.connect()
        if self._any_dirty() and not messagebox.askyesno(
                "Unsaved changes", "Reading from the mouse will discard your unsaved changes. Continue?"):
            return

        def done(snap):
            self.fill(snap)
            self.toast.show("Settings read from the mouse", "ok", 1800)
        self.run_bg(self.dev.snapshot, done, "Reading settings…")

    def _any_dirty(self) -> bool:
        return any(p.dirty for p in self.pages.values())

    def fill(self, snap: dict) -> None:
        self.snap = snap
        self.status = self.dev.last_status
        self.caps = capabilities(self.status.chip)
        self.empty.place_forget()
        self._show_status()
        self.profile_var.set(snap["profile"] + 1)
        for p in self.pages.values():
            p.reload()
        self.refresh_var.set(f"Updated {time.strftime('%H:%M:%S')}")
        self.refresh_footer()

    def _show_status(self) -> None:
        st = self.status
        if st is None:
            return
        linked = st.connected
        self.dot.itemconfigure(self.dot_item, fill=T.OK if linked else T.WARN)
        self.conn_var.set("Connected" if linked else "Dongle only")
        extra = ""
        if len(self.entries) > 1 and self.entry:
            pos = next((i for i, e in enumerate(self.entries) if e.key == self.entry.key), None)
            if pos is not None:
                extra = f" · {pos + 1} of {len(self.entries)} mice"
        self.sub_var.set(f"Sensor {st.chip_name}{extra}" + ("" if linked else " · mouse asleep / out of range"))
        self.bat_var.set(f"{st.battery}%" + ("  · charging" if st.charging else ""))
        self._draw_battery()

    def _draw_battery(self) -> None:
        self.bat.delete("all")
        st = self.status
        if st is None:
            return
        w, h = self.bat.winfo_width(), px(8)
        if w <= 2:
            return
        self.bat.create_rectangle(0, 0, w, h, fill=T.SURFACE3, outline="")
        col = T.OK if st.battery > 30 else (T.WARN if st.battery > 15 else T.DANGER)
        self.bat.create_rectangle(0, 0, int(w * st.battery / 100), h, fill=T.ACCENT if st.charging else col, outline="")

    def switch_profile(self) -> None:
        if not self.dev:
            return
        n = self.profile_var.get() - 1
        if n == self.snap.get("profile"):
            return
        if self._any_dirty() and not messagebox.askyesno(
                "Unsaved changes", "Switching profile will discard your unsaved changes. Continue?"):
            self.profile_var.set(self.snap["profile"] + 1)
            return

        def work():
            self.dev.set_profile(n)
            return self.dev.snapshot()

        def done(snap):
            self.fill(snap)
            self.toast.show(f"Profile {n + 1} is now active", "ok", 2000)
        self.run_bg(work, done, "Switching profile…")

    # ------------------------------------------------------------------ apply / discard
    def apply_current(self) -> None:
        page = self.pages[self.current]
        if not self.dev or not page.dirty:
            return
        try:
            fn = page.make_apply()
        except ValueError as e:
            self.toast.show(str(e), "error")
            return

        def done(partial):
            _merge(self.snap, partial)
            page.dirty = False
            for p in self.pages.values():
                if not p.dirty:
                    p.reload()
            self.refresh_footer()
            self.toast.show("Nothing written (dry run)" if self.dry_run else "Saved to the mouse", "ok", 2200)
            self.refresh_var.set(f"Saved {time.strftime('%H:%M:%S')}")
        self.run_bg(fn, done, "Writing to the mouse…")

    def discard_current(self) -> None:
        page = self.pages[self.current]
        page.reload()
        self.refresh_footer()

    # ------------------------------------------------------------------ auto refresh
    INTERVALS = (1, 2, 3, 5, 10, 15, 30, 60, 120, 300, 600, 1800, 3600)

    def interval(self) -> int:
        """Refresh interval in seconds (1..3600); falls back to 10 for unusable input."""
        try:
            return min(3600, max(1, int(float(self.auto_secs.get()))))
        except ValueError:
            return 10

    def _save_prefs(self) -> None:
        if not self.mock:
            S.save(auto_refresh=bool(self.auto_var.get()), auto_secs=self.interval())

    def _on_auto_toggle(self) -> None:
        self._save_prefs()
        self._schedule_auto()

    def _commit_interval(self) -> None:
        self.auto_secs.set(str(self.interval()))
        self._save_prefs()
        self._schedule_auto()

    def _step_interval(self, direction: int) -> None:
        cur = self.interval()
        if direction > 0:
            nxt = next((v for v in self.INTERVALS if v > cur), self.INTERVALS[-1])
        else:
            nxt = next((v for v in reversed(self.INTERVALS) if v < cur), self.INTERVALS[0])
        self.auto_secs.set(str(nxt))
        self._save_prefs()
        self._schedule_auto()

    def _schedule_auto(self) -> None:
        if self._auto_after is not None:
            self.after_cancel(self._auto_after)
            self._auto_after = None
        if self.auto_var.get():
            self._auto_after = self.after(self.interval() * 1000, self._auto_tick)

    def _auto_tick(self) -> None:
        if self._auto_after is not None:
            try:
                self.after_cancel(self._auto_after)
            except tk.TclError:
                pass
            self._auto_after = None
        if self.auto_var.get():
            source = self.source
            if self.dev is not None:
                dev, cur = self.dev, (self.entry.key if self.entry else None)

                def work():
                    sig = source.signature()
                    scan = None
                    if sig != self._sig:                       # a mouse was plugged in or removed
                        scan = (source.scan(), sig)
                        if cur and not any(e.key == cur for e in scan[0]):
                            return ("lost", None, scan)
                    st = dev.status()
                    prof = dev.get_profile()
                    if prof != self.snap.get("profile"):
                        return ("full", dev.snapshot(), scan)
                    d = dev.get_dpi()
                    return ("light", dict(status=st, dpi={"values": d.values, "enabled": d.enabled,
                                                          "current": d.current, "colors": d.colors},
                                          rate=dev.get_report_rate()), scan)
                self.run_bg(work, self._auto_done, quiet=True)
            else:                                              # nothing connected: wait for a mouse to show up
                def work():
                    return ("scan", None, (source.scan(), source.signature()))
                self.run_bg(work, self._auto_done, quiet=True)
        self._schedule_auto()

    def _auto_done(self, res) -> None:
        kind, data, scan = res
        stamp = time.strftime("%H:%M:%S")
        if scan is not None:
            self._apply_scan(*scan)
        if kind in ("lost", "scan"):
            return
        if kind == "full":
            if self._any_dirty():
                self.snap["profile"] = data["profile"]
                self.profile_var.set(data["profile"] + 1)
                self.toast.show("Profile changed on the mouse \u2014 press Discard to load it", "info", 4000)
            else:
                self.fill(data)
                self.toast.show(f"Profile {data['profile'] + 1} selected on the mouse", "info", 2500)
        else:
            self.status = data["status"]
            self._show_status()
            changed = data["dpi"] != self.snap.get("dpi") or data["rate"] != self.snap.get("report_rate")
            if changed:
                self.snap["dpi"], self.snap["report_rate"] = data["dpi"], data["rate"]
                for p in self.pages.values():
                    if not p.dirty:
                        p.reload()
        self.refresh_var.set(f"Refreshed {stamp}")

    def _close(self) -> None:
        self.destroy()

    def destroy(self) -> None:
        for attr in ("_pump_after", "_auto_after"):
            job = getattr(self, attr, None)
            if job:
                try:
                    self.after_cancel(job)
                except tk.TclError:
                    pass
                setattr(self, attr, None)
        if getattr(self, "toast", None) is not None:
            self.toast.cancel()
        if self.dev:
            try:
                self.dev.close()
            except Exception:  # noqa: BLE001
                pass
            self.dev = None
        super().destroy()


def _merge(dst: dict, src: dict) -> None:
    for k, v in src.items():
        if isinstance(v, dict) and isinstance(dst.get(k), dict):
            _merge(dst[k], v)
        else:
            dst[k] = v


def run(mock: bool = False, dry_run: bool = False, device: int | None = None) -> None:
    _enable_dpi_awareness()
    App(mock=mock, dry_run=dry_run, device=device).mainloop()
