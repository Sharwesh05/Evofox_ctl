"""Command line interface:  python -m ghostx <command>"""

from __future__ import annotations

import argparse
import json
import sys

from . import dpi as D
from . import keys as K
from . import macros as M
from . import protocol as P
from .device import GhostX, REPORT_RATES_HZ, SCENE_MODES, Settings
from .transport import TransportError, enumerate_devices


def get_source(args):
    from .devices import MockSource, RealSource
    return MockSource() if args.mock else RealSource()


def connect(args) -> GhostX:
    from .devices import pick
    log = (lambda s: print("  ", s, file=sys.stderr)) if args.verbose else None
    entries = get_source(args).scan()
    if args.device is None and len(entries) > 1 and not args.mock:
        print(f"note: {len(entries)} mice found, using #0 ({entries[0].label}); "
              "choose another with --device N (see `ghostx list`)", file=sys.stderr)
    entry = pick(entries, args.device or 0)
    import time
    sleep = (lambda s: None) if args.mock else time.sleep
    return GhostX(entry.open(), dry_run=args.dry_run, log=log, sleep=sleep)


def _button_index(name: str) -> int:
    if name.isdigit():
        i = int(name)
        if i >= len(K.BUTTONS):
            raise SystemExit(f"button index must be 0..{len(K.BUTTONS) - 1}")
        return i
    if name in K.BUTTONS:
        return K.BUTTONS.index(name)
    raise SystemExit(f"unknown button {name!r}; choose from {', '.join(K.BUTTONS)}")


# -------------------------------------------------------------------------------------------
def cmd_list(args):
    if args.all:                                     # raw HID interfaces (diagnostics)
        devs = enumerate_devices()
        if not devs:
            print("no EvoFox Ghost X found")
            return 1
        for d in devs:
            print(f"{d.kind:6} vid={d.vendor_id:04x} pid={d.product_id:04x} usage={d.usage_page:04x}/{d.usage:04x} "
                  f"feature_len={d.feature_len} config={'yes' if d.has_config_report else 'no'}  {d.product}")
            print(f"       {d.path}")
        return 0
    entries = get_source(args).scan()
    if not entries:
        print("no EvoFox Ghost X found (is the mouse / dongle plugged in?)")
        return 1
    print("Select with: ghostx --device N <command>\n")
    for i, e in enumerate(entries):
        print(f"  [{i}] {e.label}")
        if args.verbose:
            print(f"      {e.key}")
    return 0


def cmd_actions(args):
    _help_functions()


def _help_functions() -> None:
    print("Button / wheel functions  (use with: ghostx button <name> <function>)\n")
    width = max(len(n) for g in K.ACTION_HELP.values() for n, _ in g) + 2
    for group, items in K.ACTION_HELP.items():
        print(group)
        for name, text in items:
            print(f"  {name:<{width}}{text}")
        print()
    print("Buttons:", ", ".join(K.BUTTONS), "  (or index 0-5)")
    print("Wheel  :", ", ".join(K.WHEEL))


_OVERVIEW = """\
ghostx - EvoFox Ghost X configuration tool

USAGE   ghostx [--mock] [--dry-run] [-v] <command> [options]

READ
  info                  show the whole device state
  dump [-o FILE]        save the active profile as JSON
  list                  list connected mice (cable, dongle, several mice)

CHANGE
  dpi                   DPI stages, enabled stages, active stage, stage colours
  rate [HZ]             polling rate (125 250 500 1000 2000 4000 8000)
  button NAME [FUNC]    assign a button function
  wheel up|down [FUNC]  assign a wheel function
  macro BUTTON [FILE]   show or store a macro
  settings              sleep time, debounce, scene mode, sensor options
  profile [1-3]         show / switch hardware profile
  apply FILE            write a saved profile JSON

OTHER
  gui                   graphical interface
  actions               list button functions (same as: help functions)
  help [TOPIC]          this help; TOPIC = a command name, or: functions, keys, macros, safety

GLOBAL FLAGS
  --mock       simulated mouse, no hardware access
  --dry-run    read from the mouse but never write
  -d, --device N   choose a mouse when several are connected (numbers from `ghostx list`)
  -v           log every protocol transaction

Examples:
  ghostx list
  ghostx --device 1 info
  ghostx rate 1000
  ghostx dpi --stage 3 1800 --current 3
  ghostx button back key:ctrl+shift+a
  ghostx --dry-run apply backup.json
"""


def _help_keys() -> None:
    print("Key names for key:<combo> (join with +, max 3 keys):\n  " + ", ".join(sorted(K.HID_KEYS))
          + "\n\nA plain number is taken as a raw HID usage id.")


def _help_macros() -> None:
    print("""\
Macros: a text file, one step per line (several per line with ';', '#' starts a comment)

  down a          press key a             up a            release key a
  press a         press + release         click left      mouse click (left right middle back forward)
  delay 30        wait 30 ms after the previous step
  dpi 800         change DPI              move 5 -5       relative pointer move

Store : ghostx macro left my.txt [--repeat N] [--type 0|1|2] [--random-delay MS] [--fixed-delay MS] [--assign]
        --type 0 repeat N times, 1 repeat while held, 2 repeat until pressed again
Show  : ghostx macro left
Limits: 512 bytes per macro; not available on the scroll wheel.""")


def _help_safety() -> None:
    print("""\
- The bootloader (firmware update) command is never sent.
- Only HID interfaces of the Ghost X vendor id are opened.
- Factory parameters (key count) are read-only.
- --dry-run reads but never writes; --mock never touches hardware.
- Back up first:  ghostx dump -o backup.json   (restore with: ghostx apply backup.json)""")


_TOPICS = {"keys": _help_keys, "macros": _help_macros, "safety": _help_safety}


def cmd_help(args):
    topic = (args.topic or "").lower()
    if not topic:
        print(_OVERVIEW)
        return 0
    if topic in ("functions", "function", "actions"):
        _help_functions()
        return 0
    if topic in _TOPICS:
        _TOPICS[topic]()
        return 0
    sub = next(a for a in build_parser()._actions if isinstance(a, argparse._SubParsersAction))
    if topic in sub.choices:
        sub.choices[topic].print_help()
        return 0
    print(f"no help for {topic!r}. Topics: functions, keys, macros, safety, or a command: "
          + ", ".join(sub.choices), file=sys.stderr)
    return 2


def cmd_info(args):
    with connect(args) as dev:
        s = dev.status()
        print(f"link        : {'connected' if s.connected else 'mouse not linked to dongle'}")
        print(f"battery     : {s.battery}%{' (charging)' if s.charging else ''}")
        print(f"sensor chip : {s.chip_name}")
        print(f"profile     : {dev.get_profile() + 1} of {P.PROFILE_COUNT}")
        print(f"report rate : {dev.get_report_rate()} Hz")
        dpi = dev.get_dpi()
        print(f"DPI stages  : current = {dpi.current}")
        for i, (v, e, c) in enumerate(zip(dpi.values, dpi.enabled, dpi.colors), 1):
            print(f"   {i}{'*' if i == dpi.current else ' '} {v if v is not None else '?':>6} DPI  "
                  f"{'on ' if e else 'off'} {c}")
        st = dev.get_settings()
        print(f"settings    : sleep {st.sleep_seconds // 60} min, debounce {st.debounce_ms} ms, "
              f"move-to-wake {st.move_to_wake}, scene {SCENE_MODES[st.scene_mode]}")
        for i, n in enumerate(K.BUTTONS):
            print(f"button {n:8}: {dev.get_button(i)['function']}")
        for i, n in enumerate(K.WHEEL):
            print(f"wheel  {n:8}: {dev.get_button(i, wheel=True)['function']}")


def cmd_dump(args):
    with connect(args) as dev:
        text = json.dumps(dev.snapshot(), indent=2)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(text + "\n")
        print(f"saved {args.output}")
    else:
        print(text)


def cmd_apply(args):
    with open(args.file, encoding="utf-8") as f:
        snap = json.load(f)
    with connect(args) as dev:
        dev.apply_snapshot(snap)
    print("profile applied")


def cmd_profile(args):
    with connect(args) as dev:
        if args.number is None:
            print(dev.get_profile() + 1)
        else:
            dev.set_profile(args.number - 1)
            print(f"switched to profile {args.number}")


def cmd_dpi(args):
    with connect(args) as dev:
        if not any((args.values, args.enable, args.current, args.stage, args.colors)):
            st = dev.get_dpi()
            for i, (v, e, c) in enumerate(zip(st.values, st.enabled, st.colors), 1):
                print(f"{i}{'*' if i == st.current else ' '} {v} DPI {'on' if e else 'off'} {c}")
            lo, hi = D.min_max(dev.chip)
            print(f"sensor range {lo}-{hi} DPI")
            return
        values = enabled = colors = None
        if args.values:
            values = [int(x) for x in args.values.split(",")]
        if args.stage:
            st = dev.get_dpi()
            values = [v or D.table(dev.chip)[0].dpi for v in st.values]
            n, v = args.stage
            values[int(n) - 1] = int(v)
        if args.enable:
            on = {int(x) for x in args.enable.split(",")}
            enabled = [(i + 1) in on for i in range(P.MAX_DPI_GEAR)]
        if args.colors:
            colors = [D.parse_color(c) for c in args.colors.split(",")]
            if len(colors) == 1:
                colors = colors * P.MAX_DPI_GEAR
            elif len(colors) != P.MAX_DPI_GEAR:
                raise ValueError("give 8 colours (one per stage) or a single colour for all stages")
        dev.set_dpi(values=values, enabled=enabled, current=args.current, colors=colors)
        print("DPI updated")


def cmd_rate(args):
    with connect(args) as dev:
        if args.hz is None:
            print(dev.get_report_rate())
        else:
            dev.set_report_rate(args.hz)
            print(f"report rate set to {args.hz} Hz")


def cmd_button(args, wheel=False):
    with connect(args) as dev:
        idx = args.which if wheel else _button_index(args.which)
        if wheel:
            idx = K.WHEEL.index(idx)
        if args.function is None:
            print(json.dumps(dev.get_button(idx, wheel=wheel), indent=2))
            return
        dev.set_button(idx, args.function, wheel=wheel, fire_interval=args.fire_interval)
        print(f"{'wheel' if wheel else 'button'} {args.which} -> {args.function}")


def cmd_macro(args):
    with connect(args) as dev:
        idx = _button_index(args.button)
        if args.file is None:
            m = dev.read_macro(idx)
            print(m.to_text())
            return
        with open(args.file, encoding="utf-8") as f:
            text = f.read()
        macro = M.Macro.from_text(text, repeat=args.repeat, repeat_type=args.type,
                                  random_delay=args.random_delay, fixed_delay=args.fixed_delay,
                                  assign_open=args.assign)
        dev.set_button(idx, {"function": "macro", "macro": macro.to_dict()})
        print(f"macro with {len(macro.steps)} steps stored on button {args.button}")


def cmd_settings(args):
    with connect(args) as dev:
        s = dev.get_settings()
        changed = False
        if args.sleep is not None:
            s.sleep_seconds, changed = args.sleep * 60, True
        if args.debounce is not None:
            s.debounce_ms, changed = args.debounce, True
        if args.move_wake is not None:
            s.move_to_wake, changed = args.move_wake == "on", True
        if args.scene is not None:
            s.scene_mode, changed = SCENE_MODES.index(args.scene), True
        if args.lod is not None:
            s.lod, changed = args.lod, True
        for name in ("track_optimization", "motion_sync", "ripple_or_jitter", "line_correction"):
            v = getattr(args, name)
            if v is not None:
                setattr(s, name, v == "on")
                changed = True
        if changed:
            dev.set_settings(s)
            print("settings updated")
        else:
            print(json.dumps(s.__dict__, indent=2))


def cmd_gui(args):
    from .gui import run
    run(mock=args.mock, dry_run=args.dry_run, device=args.device)


# -------------------------------------------------------------------------------------------
def _int_range(lo: int, hi: int):
    def parse(text: str) -> int:
        try:
            v = int(text)
        except ValueError:
            raise argparse.ArgumentTypeError(f"{text!r} is not a number")
        if not lo <= v <= hi:
            raise argparse.ArgumentTypeError(f"must be between {lo} and {hi}")
        return v
    return parse


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="ghostx", description="EvoFox Ghost X configuration tool")
    ap.add_argument("--mock", action="store_true", help="use a simulated mouse (no hardware access)")
    ap.add_argument("--dry-run", action="store_true", help="read from the device but never write")
    ap.add_argument("-v", "--verbose", action="store_true", help="log every protocol transaction")
    ap.add_argument("-d", "--device", type=int, metavar="N",
                    help="which mouse to use when several are connected (see `ghostx list`; default 0)")
    sub = ap.add_subparsers(dest="command", required=True)

    p = sub.add_parser("list", help="list the connected mice")
    p.add_argument("-a", "--all", action="store_true", help="show raw HID interfaces instead (diagnostics)")
    p.set_defaults(fn=cmd_list)
    sub.add_parser("actions", help="list button functions").set_defaults(fn=cmd_actions)
    p = sub.add_parser("help", help="overview, command help, or topic: functions, keys, macros, safety")
    p.add_argument("topic", nargs="?")
    p.set_defaults(fn=cmd_help)
    sub.add_parser("info", help="show the whole device state").set_defaults(fn=cmd_info)
    sub.add_parser("gui", help="open the graphical interface").set_defaults(fn=cmd_gui)

    p = sub.add_parser("dump", help="save the active profile as JSON")
    p.add_argument("-o", "--output")
    p.set_defaults(fn=cmd_dump)
    p = sub.add_parser("apply", help="write a profile JSON to the device")
    p.add_argument("file")
    p.set_defaults(fn=cmd_apply)

    p = sub.add_parser("profile", help="show / switch the active profile (1-3)")
    p.add_argument("number", nargs="?", type=int, choices=range(1, P.PROFILE_COUNT + 1))
    p.set_defaults(fn=cmd_profile)

    p = sub.add_parser("dpi", help="show / change DPI stages")
    p.add_argument("--values", help="8 comma separated DPI values")
    p.add_argument("--stage", nargs=2, metavar=("N", "DPI"), help="change a single stage")
    p.add_argument("--enable", help="comma separated stages to enable, e.g. 1,2,3")
    p.add_argument("--current", type=int, choices=range(1, 9))
    p.add_argument("--colors", help="8 comma separated #RRGGBB colours, one per stage (or one colour for all)")
    p.set_defaults(fn=cmd_dpi)

    p = sub.add_parser("rate", help="show / set the polling rate")
    p.add_argument("hz", nargs="?", type=int, choices=REPORT_RATES_HZ)
    p.set_defaults(fn=cmd_rate)

    for name, wheel in (("button", False), ("wheel", True)):
        p = sub.add_parser(name, help=f"show / assign a {'wheel direction' if wheel else 'button'} function")
        p.add_argument("which", choices=list(K.WHEEL) if wheel else None,
                       metavar="up|down" if wheel else "left|middle|right|back|forward|dpi|0-5")
        p.add_argument("function", nargs="?", help="see `ghostx actions`")
        p.add_argument("--fire-interval", type=int, default=50, help="ms between fire-key clicks")
        p.set_defaults(fn=(lambda a, w=wheel: cmd_button(a, w)))

    p = sub.add_parser("macro", help="show / store a macro on a button")
    p.add_argument("button")
    p.add_argument("file", nargs="?", help="text file with one step per line (down a / up a / click left / "
                   "delay 20 / dpi 800 / move 5 -5)")
    p.add_argument("--repeat", type=int, default=1)
    p.add_argument("--type", type=int, default=0, choices=(0, 1, 2),
                   help="0 repeat N times, 1 repeat while held, 2 repeat until pressed again")
    p.add_argument("--random-delay", type=_int_range(5, 100), default=None, metavar="MS",
                   help="randomise delays by up to +-MS (5-100); shorter delays are lengthened to MS+50")
    p.add_argument("--fixed-delay", type=int, default=None, metavar="MS",
                   help="use the same delay after every step instead of each step's own")
    p.add_argument("--assign", action="store_true",
                   help="assignment macro: pressing the button hands the macro to the left button")
    p.set_defaults(fn=cmd_macro)

    p = sub.add_parser("settings", help="power / sensor settings")
    p.add_argument("--sleep", type=int, choices=range(1, 31), metavar="MIN")
    p.add_argument("--debounce", type=int, choices=range(1, 21), metavar="MS")
    p.add_argument("--move-wake", choices=("on", "off"))
    p.add_argument("--scene", choices=SCENE_MODES)
    p.add_argument("--lod", type=int, choices=(0, 1))
    for n in ("track_optimization", "motion_sync", "ripple_or_jitter", "line_correction"):
        p.add_argument("--" + n.replace("_", "-"), dest=n, choices=("on", "off"))
    p.set_defaults(fn=cmd_settings)
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.fn(args) or 0
    except (TransportError, P.ProtocolError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130
