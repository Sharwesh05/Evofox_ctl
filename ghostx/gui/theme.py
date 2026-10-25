"""Design tokens."""

BG = "#0d0f13"          # window background
SIDEBAR = "#11141a"
SURFACE = "#171b22"     # cards
SURFACE2 = "#1e232c"    # inputs, chips
SURFACE3 = "#272d38"    # hover
BORDER = "#2a303b"
TEXT = "#e9ebf0"
MUTED = "#8c94a4"
FAINT = "#5b6272"
ACCENT = "#ff5a1f"
ACCENT_HOVER = "#ff7440"
ACCENT_DIM = "#3b2218"
ACCENT_TEXT = "#ffffff"
OK = "#34d399"
WARN = "#fbbf24"
DANGER = "#f87171"

FONT = "Segoe UI"
FONT_SEMI = "Segoe UI Semibold"

# (family, size[, style]) helpers -- sizes are points so Tk scales them with the display
def font(size: int = 10, bold: bool = False):
    return (FONT_SEMI if bold else FONT, size)


_scale = 1.0


def set_scale(value: float) -> None:
    global _scale
    _scale = value


def px(n: float) -> int:
    """Scale a design pixel to the display."""
    return max(1, int(round(n * _scale))) if n else 0


def mix(c1: str, c2: str, t: float) -> str:
    """Linear blend of two #rrggbb colours."""
    a = [int(c1[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(c2[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * t):02x}" for x, y in zip(a, b))
