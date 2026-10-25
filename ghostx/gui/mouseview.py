"""Picture of the Ghost X with clickable button zones.

The photo (``assets/ghostx_mouse_<height>.png``, pre-rendered at several sizes) is shown when available; the
zones are laid over the real buttons.  If the assets cannot be loaded a vector drawing is used instead.
"""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from typing import Callable

from . import theme as T

W, H = 560, 476           # design size of the canvas
CX = 280
IMG_H = 440               # the mouse photo is this tall in design units
IMG_TOP = (H - IMG_H) // 2
ASSET_DIR = Path(__file__).resolve().parent / "assets"
_IMG_W_PX, _IMG_H_PX = 348.0, 620.0     # the frame the normalised zone coordinates below were measured in


def _n(points):
    return [(x / _IMG_W_PX, y / _IMG_H_PX) for x, y in points]


def _mirror(points):
    return [(_IMG_W_PX - x, y) for x, y in points]


_LEFT = [(52, 95), (80, 45), (130, 28), (172, 28), (172, 84), (153, 84), (153, 190), (172, 190), (172, 262),
         (95, 255), (52, 235)]
# zone -> geometry in photo pixels (348x620 frame), label side, anchor point, label height (fraction of photo)
PHOTO_ZONES = {
    "left": dict(poly=_n(_LEFT), side="L", anchor=_n([(70, 140)])[0], ly=0.17, name="Left button"),
    "right": dict(poly=_n(_mirror(_LEFT)), side="R", anchor=_n([(280, 130)])[0], ly=0.07, name="Right button"),
    "forward": dict(poly=_n([(18, 158), (44, 158), (44, 230), (18, 230)]), side="L", anchor=_n([(20, 194)])[0],
                    ly=0.36, name="Forward (side)"),
    "back": dict(poly=_n([(18, 280), (44, 280), (44, 368), (18, 368)]), side="L", anchor=_n([(20, 324)])[0],
                 ly=0.55, name="Back (side)"),
    "up": dict(poly=_n([(156, 86), (192, 86), (192, 120), (156, 120)]), side="R", anchor=_n([(192, 103)])[0],
               ly=0.17, name="Wheel up"),
    "middle": dict(poly=_n([(156, 122), (192, 122), (192, 154), (156, 154)]), side="R",
                   anchor=_n([(192, 138)])[0], ly=0.27, name="Wheel click"),
    "down": dict(poly=_n([(156, 156), (192, 156), (192, 188), (156, 188)]), side="R", anchor=_n([(192, 172)])[0],
                 ly=0.37, name="Wheel down"),
    "dpi": dict(poly=_n([(160, 214), (188, 214), (188, 264), (160, 264)]), side="R", anchor=_n([(188, 239)])[0],
                ly=0.47, name="DPI button"),
}

# vector fallback (design coordinates)
_VLEFT = [(228, 50), (276, 50), (276, 205), (197, 205), (199, 120), (206, 78)]
VECTOR_ZONES = {
    "left": dict(poly=_VLEFT, smooth=True, side="L", anchor=(215, 110), ly=92, name="Left button"),
    "right": dict(poly=[(2 * CX - x, y) for x, y in _VLEFT][::-1], smooth=True, side="R", anchor=(345, 90), ly=62,
                  name="Right button"),
    "forward": dict(rect=(174, 160, 191, 200), side="L", anchor=(176, 180), ly=182, name="Forward (side)"),
    "back": dict(rect=(174, 210, 191, 252), side="L", anchor=(176, 231), ly=240, name="Back (side)"),
    "up": dict(rect=(268, 94, 292, 120), side="R", anchor=(292, 107), ly=112, name="Wheel up"),
    "middle": dict(rect=(268, 124, 292, 160), side="R", anchor=(292, 142), ly=162, name="Wheel click"),
    "down": dict(rect=(268, 164, 292, 190), side="R", anchor=(292, 177), ly=212, name="Wheel down"),
    "dpi": dict(rect=(266, 206, 294, 228), side="R", anchor=(294, 217), ly=262, name="DPI button"),
}
VECTOR_BODY = [(228, 34), (332, 34), (364, 68), (375, 150), (377, 250), (369, 340), (346, 410), (280, 434),
               (214, 410), (191, 340), (183, 250), (185, 150), (196, 68)]


def round_rect(c: tk.Canvas, x1, y1, x2, y2, r, **kw):
    pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2, x2 - r, y2, x1 + r, y2,
           x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
    return c.create_polygon(pts, smooth=True, **kw)


def _load_zones() -> dict:
    """Button positions that belong to the artwork (``assets/zones.json``), else the built-in ones."""
    try:
        import json
        raw = json.loads((ASSET_DIR / "zones.json").read_text(encoding="utf-8"))
        zones = {}
        for zid, z in raw.items():
            zones[zid] = dict(poly=[tuple(p) for p in z["poly"]], side=z["side"], anchor=tuple(z["anchor"]),
                              ly=float(z["ly"]), name=z["name"])
        if set(zones) == set(PHOTO_ZONES):
            return zones
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return PHOTO_ZONES


def _load_photo(desired_scale: float):
    """The pre-rendered mouse closest to the wanted scale -> (PhotoImage, actual scale, aspect) or None."""
    try:
        files = sorted((int(p.stem.rsplit("_", 1)[1]), p) for p in ASSET_DIR.glob("ghostx_mouse_*.png"))
        if not files:
            return None
        want = IMG_H * desired_scale
        height, path = min(files, key=lambda f: abs(f[0] - want))
        img = tk.PhotoImage(file=str(path))
        return img, height / IMG_H, img.width() / img.height()
    except (OSError, ValueError, tk.TclError):
        return None


class MouseView(tk.Canvas):
    def __init__(self, master, on_select: Callable[[str], None] | None = None, interactive: bool = True,
                 bg: str = T.SURFACE, zoom: float = 1.0):
        want = T._scale * zoom
        photo = _load_photo(want)
        self.photo = photo[0] if photo else None
        scale = photo[1] if photo else want
        self.aspect = photo[2] if photo else None
        super().__init__(master, width=int(W * scale), height=int(H * scale), bg=bg, bd=0, highlightthickness=0)
        self._scale = scale
        self.on_select, self.interactive = on_select, interactive
        self.selected: str | None = None
        self.items: dict[str, int] = {}
        self.name_items: dict[str, int] = {}
        self.fn_items: dict[str, int] = {}
        self.zones = self._zones()
        self._draw(bg)
        self.scale("all", 0, 0, scale, scale)

    # ------------------------------------------------------------------ geometry
    def _zones(self) -> dict:
        if self.photo is None:
            return VECTOR_ZONES
        img_w = IMG_H * self.aspect
        self._half_w = img_w / 2
        zones = {}
        for zid, z in _load_zones().items():
            def to_design(p):
                return (CX + (p[0] - 0.5) * img_w, IMG_TOP + p[1] * IMG_H)
            zones[zid] = dict(poly=[to_design(p) for p in z["poly"]], side=z["side"], name=z["name"],
                              anchor=to_design(z["anchor"]), ly=IMG_TOP + z["ly"] * IMG_H, smooth=False)
        return zones

    def _label_x(self, side: str) -> float:
        if self.photo is None:
            return 150 if side == "L" else 410
        return CX - self._half_w - 10 if side == "L" else CX + self._half_w + 10

    # ------------------------------------------------------------------ drawing
    def _draw(self, bg: str):
        for z in self.zones.values():                          # leader lines first, so artwork draws over them
            self._line(z)
        if self.photo is not None:
            self.create_image(CX, IMG_TOP, image=self.photo, anchor="n")
        else:
            self.create_polygon([c for p in VECTOR_BODY for c in p], smooth=True, splinesteps=24,
                                fill=T.mix(T.SURFACE, "#000000", 0.25), outline=T.SURFACE3, width=2)
            self.create_text(CX, 340, text="GHOST X", fill=T.FAINT, font=T.font(9, True))
        for zid, z in self.zones.items():
            if "rect" in z:
                x1, y1, x2, y2 = z["rect"]
                item = round_rect(self, x1, y1, x2, y2, 5, fill=T.SURFACE2, outline=T.BORDER, width=1.5)
            else:
                item = self.create_polygon([c for p in z["poly"] for c in p], smooth=z.get("smooth", False),
                                           splinesteps=16, fill=T.SURFACE2, outline=T.BORDER, width=1.5)
            self.items[zid] = item
            self._callout(zid, z)
            self._paint(zid)
        self.hover: str | None = None
        self.bind("<Motion>", self._on_motion)
        self.bind("<Leave>", lambda e: self._set_hover(None))
        self.bind("<Button-1>", self._on_click)

    def _line(self, z: dict):
        ax, ay = z["anchor"]
        lx = self._label_x(z["side"])
        ex = lx + (6 if z["side"] == "L" else -6)
        self.create_line(ax, ay, ex - (4 if z["side"] == "L" else -4), z["ly"], fill=T.SURFACE3, width=1)

    def _callout(self, zid: str, z: dict):
        ax, ay = z["anchor"]
        lx = self._label_x(z["side"])
        anchor = "e" if z["side"] == "L" else "w"
        ly = z["ly"]
        self.create_oval(ax - 2.5, ay - 2.5, ax + 2.5, ay + 2.5, fill=T.ACCENT if self.photo else T.FAINT, outline="")
        self.name_items[zid] = self.create_text(lx, ly - 9, text=z["name"], anchor=anchor, fill=T.MUTED,
                                                font=T.font(8))
        self.fn_items[zid] = self.create_text(lx, ly + 6, text="", anchor=anchor, fill=T.TEXT,
                                              font=T.font(10, True))

    # ------------------------------------------------------------------ state
    def _paint(self, zid: str, hover: bool = False):
        item = self.items[zid]
        sel = zid == self.selected
        hover = hover or zid == getattr(self, "hover", None)
        if self.photo is not None:
            # outlines only when idle; a translucent (stippled) accent wash on hover / selection
            if sel:
                self.itemconfigure(item, fill=T.ACCENT, stipple="gray50", outline=T.ACCENT, width=2.5, dash=())
            elif hover and self.interactive:
                self.itemconfigure(item, fill=T.ACCENT, stipple="gray25", outline=T.ACCENT_HOVER, width=1.5, dash=())
            else:
                self.itemconfigure(item, fill="", stipple="", outline="#7d8699", width=1, dash=(3, 4))
        elif sel:
            self.itemconfigure(item, fill=T.ACCENT_DIM, outline=T.ACCENT)
        else:
            self.itemconfigure(item, fill=T.SURFACE3 if hover and self.interactive else T.SURFACE2,
                               outline=T.BORDER)
        self.itemconfigure(self.name_items[zid], fill=T.ACCENT if sel else T.MUTED)

    # ------------------------------------------------------------------ hit testing
    @staticmethod
    def _inside(pt, poly) -> bool:
        x, y = pt
        inside = False
        n = len(poly)
        for i in range(n):
            x1, y1 = poly[i]
            x2, y2 = poly[(i + 1) % n]
            if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
                inside = not inside
        return inside

    def zone_at(self, px_x: float, px_y: float) -> str | None:
        """Zone under a canvas pixel position (shapes first, then the text labels)."""
        pt = (px_x / self._scale, px_y / self._scale)
        for zid in reversed(list(self.zones)):                  # later zones (wheel, DPI) sit on top
            z = self.zones[zid]
            if "rect" in z:
                x1, y1, x2, y2 = z["rect"]
                hit = x1 <= pt[0] <= x2 and y1 <= pt[1] <= y2
            else:
                hit = self._inside(pt, z["poly"])
            if hit:
                return zid
        for zid in self.zones:
            box = self.bbox(self.name_items[zid], self.fn_items[zid])
            if box and box[0] <= px_x <= box[2] and box[1] <= px_y <= box[3]:
                return zid
        return None

    def _on_motion(self, e):
        self._set_hover(self.zone_at(e.x, e.y))

    def _set_hover(self, zid: str | None):
        if zid == self.hover:
            return
        old, self.hover = self.hover, zid
        if self.interactive:
            self.configure(cursor="hand2" if zid else "")
        for z in (old, zid):
            if z:
                self._paint(z)

    def _on_click(self, e):
        zid = self.zone_at(e.x, e.y)
        if zid:
            self._click(zid)

    def _click(self, zid: str):
        if not self.interactive:
            return
        self.select(zid)
        if self.on_select:
            self.on_select(zid)

    def select(self, zid: str | None):
        old, self.selected = self.selected, zid
        for z in (old, zid):
            if z:
                self._paint(z)

    def set_functions(self, texts: dict[str, str]):
        for zid, text in texts.items():
            self.itemconfigure(self.fn_items[zid], text=text)
