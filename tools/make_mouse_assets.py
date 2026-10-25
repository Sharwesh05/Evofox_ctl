"""Build the app's mouse artwork from a product photo (development tool -- needs Pillow; the app itself does not).

    python tools/make_mouse_assets.py SOURCE.png [--erode 2] [--threshold 250] [--zones-px zones_px.json]

* removes the (near-white) background by flood-filling from the image border,
* crops to the mouse, smooths the silhouette, writes ``ghostx/gui/assets/ghostx_mouse_<height>.png`` at several sizes
  (the app picks the one closest to the display scale -- Tk can only scale images by whole factors),
* with ``--zones-px`` converts button hot-spots given in *source-image pixels* into the normalised
  ``assets/zones.json`` the app reads.  Format::

      {"left":   {"poly": [[x, y], ...], "anchor": [x, y], "side": "L", "label_y": y, "name": "Left button"}, ...}

  zones: left right forward back up middle down dpi.
"""

from __future__ import annotations

import argparse
import json
import os
from collections import deque
from pathlib import Path

from PIL import Image, ImageFilter

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "ghostx" / "gui" / "assets"
IMG_H = 440                                   # design height of the mouse inside the app (see mouseview.py)
SCALES = [0.75, 0.9, 1.05, 1.2, 1.35, 1.5, 1.65, 1.8]


def cut_out(im: Image.Image, threshold: int, erode: int):
    """Return (rgb, mask, bbox) -- mask is 255 on the mouse."""
    w, h = im.size
    px = im.load()
    bg = bytearray(w * h)
    q = deque([(x, y) for x in range(w) for y in (0, h - 1)] + [(x, y) for y in range(h) for x in (0, w - 1)])
    while q:
        x, y = q.popleft()
        if not (0 <= x < w and 0 <= y < h) or bg[y * w + x] or min(px[x, y]) < threshold:
            continue
        bg[y * w + x] = 1
        q.extend(((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)))
    mask = Image.frombytes("L", (w, h), bytes(0 if b else 255 for b in bg))
    mask = mask.filter(ImageFilter.MedianFilter(3))
    for _ in range(erode):                    # drop the anti-aliased halo left by the white background
        mask = mask.filter(ImageFilter.MinFilter(3))
    return im, mask, mask.getbbox()


def edge_tone(rgb: Image.Image, mask: Image.Image):
    """Average colour of the mouse's outermost pixels (used to fill the removed background)."""
    inner = mask.filter(ImageFilter.MinFilter(5))
    ring = Image.composite(Image.new("L", mask.size, 0), mask, inner)       # mask minus its eroded core
    px, rp = rgb.load(), ring.load()
    tot, n = [0, 0, 0], 0
    for y in range(0, mask.height, 2):
        for x in range(0, mask.width, 2):
            if rp[x, y]:
                for i in range(3):
                    tot[i] += px[x, y][i]
                n += 1
    return tuple(t // max(1, n) for t in tot)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("source")
    ap.add_argument("--threshold", type=int, default=250, help="background = pixels brighter than this")
    ap.add_argument("--erode", type=int, default=0, help="shave this many source pixels off the silhouette")
    ap.add_argument("--zones-px", help="JSON with hot-spots in source pixels (see module docstring)")
    a = ap.parse_args()

    raw = Image.open(a.source)
    has_alpha = raw.mode in ("RGBA", "LA") and raw.getchannel("A").getextrema()[0] < 250
    im = raw.convert("RGB")
    if has_alpha:                                   # the picture already has a transparent background: use it
        mask = raw.getchannel("A")
        for _ in range(a.erode):
            mask = mask.filter(ImageFilter.MinFilter(3))
        rgb, bbox = im, mask.point(lambda v: 255 if v > 8 else 0).getbbox()
        print("using the picture's own transparency")
    else:
        rgb, mask, bbox = cut_out(im, a.threshold, a.erode)
    pad = max(6, round(0.012 * max(im.size)))
    box = (max(0, bbox[0] - pad), max(0, bbox[1] - pad), min(im.width, bbox[2] + pad), min(im.height, bbox[3] + pad))
    rgb_c, m_c = rgb.crop(box), mask.crop(box)
    tone = edge_tone(rgb_c, m_c)
    rgb_c = Image.composite(rgb_c, Image.new("RGB", rgb_c.size, tone), m_c.filter(ImageFilter.MinFilter(3)))
    aspect = rgb_c.width / rgb_c.height
    print("source", im.size, "mouse bbox", bbox, "crop", rgb_c.size, "aspect", round(aspect, 4), "edge tone", tone)

    OUT.mkdir(parents=True, exist_ok=True)
    for f in OUT.glob("ghostx_mouse_*.png"):
        f.unlink()
    for s in SCALES:
        th = round(IMG_H * s)
        tw = round(th * aspect)
        k = th / rgb_c.height
        big = rgb_c.resize((tw, th), Image.LANCZOS)
        if k > 1:
            big = big.filter(ImageFilter.UnsharpMask(radius=1.4, percent=70, threshold=2))
        alpha = m_c.resize((tw, th), Image.BICUBIC).filter(ImageFilter.GaussianBlur(max(0.8, min(k, 1) * 0.9 + (k > 1) * k * 0.4)))
        alpha = alpha.point(lambda v: 0 if v < 100 else (255 if v > 160 else int((v - 100) * 255 / 60)))
        out = big.convert("RGBA")
        out.putalpha(alpha)
        path = OUT / f"ghostx_mouse_{th}.png"
        out.save(path, optimize=True)
        print(" ", path.name, out.size, path.stat().st_size // 1024, "KB")

    if a.zones_px:
        spec = json.loads(Path(a.zones_px).read_text(encoding="utf-8"))
        cw, ch = rgb_c.size

        def norm(p):
            return [round((p[0] - box[0]) / cw, 5), round((p[1] - box[1]) / ch, 5)]
        zones = {}
        for zid, z in spec.items():
            zones[zid] = {"poly": [norm(p) for p in z["poly"]], "anchor": norm(z["anchor"]), "side": z["side"],
                          "ly": round((z["label_y"] - box[1]) / ch, 5), "name": z["name"]}
        (OUT / "zones.json").write_text(json.dumps(zones, indent=1), encoding="utf-8")
        print("  zones.json written for", ", ".join(zones))
    elif (OUT / "zones.json").exists():
        print("  note: assets/zones.json is from an earlier picture -- pass --zones-px or delete it")


if __name__ == "__main__":
    main()
