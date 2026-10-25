"""Double-click launcher for the GUI (no console window)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ghostx.gui import run  # noqa: E402

run()
