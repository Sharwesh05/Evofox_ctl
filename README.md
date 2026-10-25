# ghostx – EvoFox Ghost X configuration tool (Python)

A stand-alone replacement for the vendor web configurator
(`support.amkette.com/webapp/ghostx/`), written from a reverse-engineering of that site's JavaScript
(see [RE_NOTES.md](RE_NOTES.md) for the protocol). Pure standard library on Windows
(`ctypes` + `hid.dll`), Tkinter GUI, no installation of third-party packages.

> **Status:** the read path (`ghostx info`) was run once against a real wired Ghost X and decoded
> correctly (link, battery, sensor, profile, polling rate, DPI stages, settings, buttons).
> **Write commands have not been tried on hardware** -- they were only tested against a software model of
> the firmware (`ghostx/mock.py`, 39 unit tests). Use `--dry-run` / `dump` first and keep the vendor web
> app as a fallback.

## Use

```
python -m ghostx list                 # connected mice (cable / dongle / several); no data is exchanged
python -m ghostx --device 1 info      # pick a mouse when several are connected
python -m ghostx info                 # read & show everything
python -m ghostx --dry-run apply p.json   # read from the mouse, print what *would* be written
python -m ghostx gui                  # graphical interface
python -m ghostx --mock gui           # same GUI against a simulated mouse (no hardware access)
```

| task | command |
|---|---|
| polling rate | `ghostx rate 1000` |
| DPI stages | `ghostx dpi --values 800,1200,1600,2400,3200,4800,6400,6400 --current 2` / `--stage 3 1800` / `--enable 1,2,3` / `--colors #f00,#0f0,...` (one per stage, or one for all) |
| button | `ghostx button back key:ctrl+shift+a` · `ghostx button dpi profile_cycle` · `ghostx button forward fire` |
| wheel | `ghostx wheel up scroll_up` |
| macro | (GUI: **Macros** page - library, step editor, key recorder, repeat modes, delays, random delay) `ghostx macro left macro.txt --type 1` (text file: `down a; delay 20` / `up a` / `click left` / `dpi 800` / `move 5 -5`) |
| settings | `ghostx settings --sleep 5 --debounce 6 --scene long_endurance --move-wake on` |
| profile | `ghostx profile 2` (hardware profiles 1‑3) |
| backup | `ghostx dump -o mine.json` · `ghostx apply mine.json` |
| function list | `ghostx actions` |

Add `-v` to log every protocol transaction. Writes also refresh the profile's “random id” so the
vendor web app re-reads the mouse instead of showing stale settings.

## Desktop app

`ghostx gui` (or double-click `ghostx_gui.pyw`): dark, DPI-aware window with a sidebar (Overview, Buttons,
DPI, Performance, Backup, Log), an interactive mouse illustration for assigning buttons, an
"unsaved changes -> Apply / Discard" bar, toast notifications and optional auto refresh (battery, link,
profile, active DPI stage, polling rate; pages with unsaved edits are never overwritten).
With several mice (cable, dongle, more than one mouse) the sidebar shows a device menu; plugging or
unplugging a mouse is noticed automatically when auto refresh is on, and the last used mouse is remembered.
`ghostx --mock gui` runs it against two simulated mice, `ghostx --dry-run gui` blocks all writes.

## Safety design

* never sends the bootloader command (127) – enforced in `protocol.build_frame`;
* only HID paths with the Ghost X vendor id are ever opened;
* factory parameters (key count) are read-only;
* `--dry-run` blocks every write; `--mock` never touches the HID stack;
* wired (`0x40B0`) is preferred over the dongle (`0x40C1`) when both are present.

## Layout

```
ghostx/protocol.py   frame format, commands
ghostx/transport.py  Windows hid.dll backend (+ optional hidapi on Linux/macOS)
ghostx/device.py     GhostX client: DPI, rate, buttons, macros, settings, snapshot/apply
ghostx/keys.py       button function encoding   ghostx/macros.py  macro byte format
ghostx/dpi.py        per-sensor DPI tables
ghostx/mock.py       firmware model for tests    ghostx/cli.py
ghostx/gui/          desktop app (app shell, pages, custom widgets, mouse illustration)
tests/               python -m unittest discover -s tests -t .
site/                downloaded/de-obfuscated vendor site and the scripts used to produce it
assets_src/          source mouse picture (official Amkette product image) + clickable button areas
tools/               make_mouse_assets.py - rebuilds ghostx/gui/assets from a photo (development only, needs Pillow)
```

On Linux/macOS install `hidapi` (`pip install hidapi`); the report length defaults to 65 bytes and was
not tested there.
