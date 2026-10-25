"""Build a single-file Windows executable of the GUI (development only; needs PyInstaller and Pillow).

    .venv\Scripts\python tools\build_exe.py        ->  dist\GhostX.exe
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ICON = ROOT / "build" / "ghostx.ico"


def make_icon() -> Path:
    from PIL import Image

    src = Image.open(ROOT / "ghostx" / "gui" / "assets" / "ghostx_mouse_792.png").convert("RGBA")
    side = max(src.size)
    canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    canvas.paste(src, ((side - src.width) // 2, (side - src.height) // 2))
    ICON.parent.mkdir(exist_ok=True)
    canvas.save(ICON, sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    return ICON


def main() -> int:
    sep = ";" if sys.platform == "win32" else ":"
    cmd = [
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile", "--windowed",
        "--name", "GhostX", "--icon", str(make_icon()),
        "--add-data", f"{ROOT / 'ghostx' / 'data'}{sep}ghostx/data",
        "--add-data", f"{ROOT / 'ghostx' / 'gui' / 'assets'}{sep}ghostx/gui/assets",
        "--distpath", str(ROOT / "dist"), "--workpath", str(ROOT / "build"), "--specpath", str(ROOT / "build"),
        str(ROOT / "ghostx_gui.pyw"),
    ]
    return subprocess.call(cmd, cwd=ROOT)


if __name__ == "__main__":
    sys.exit(main())
