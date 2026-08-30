"""openrazer-win CLI."""

from __future__ import annotations

import argparse
import sys

from . import __version__
from .devices import DeviceKind
from .mouse import DPIStage, RazerMouse
from .transport import DiscoveredDevice, RazerTransport, discover, enumerate_all_razer


def cmd_list(args: argparse.Namespace) -> int:
    if args.all:
        rows = enumerate_all_razer()
        if not rows:
            print("No Razer devices found on any HID interface.")
            return 1
        print(f"Found {len(rows)} raw Razer HID interfaces (VID 0x1532):")
        for r in rows:
            print(
                f"  pid=0x{r['product_id']:04x}  "
                f"usage_page=0x{r.get('usage_page', 0):04x}  "
                f"iface={r.get('interface_number', -1)}  "
                f"product={r.get('product_string') or '(none)'}"
            )
        return 0

    devs = discover()
    if not devs:
        print("No known Razer devices found on their configuration interface.")
        print("Run `openrazer-win list --all` to see every Razer HID interface,")
        print("known or not, for triage.")
        return 1
    print(f"Found {len(devs)} known Razer device(s):")
    for d in devs:
        print(
            f"  {d.spec.name}  vid=0x{d.spec.vid:04x} pid=0x{d.spec.pid:04x} "
            f"kind={d.spec.kind.value}  usage_page=0x{d.usage_page:04x}"
        )
    return 0


def _one_mouse(target: str | None) -> DiscoveredDevice:
    mice = [d for d in discover() if d.spec.kind == DeviceKind.MOUSE]
    if not mice:
        print("No known Razer mice found.", file=sys.stderr)
        sys.exit(2)
    if target:
        lower = target.lower()
        for d in mice:
            if lower in d.spec.name.lower() or target == f"0x{d.spec.pid:04x}":
                return d
        print(f"No mouse matched '{target}'.", file=sys.stderr)
        sys.exit(2)
    if len(mice) > 1:
        print("Multiple mice found — pass --device <name|pid> to disambiguate:", file=sys.stderr)
        for d in mice:
            print(f"  {d.spec.name} (pid=0x{d.spec.pid:04x})", file=sys.stderr)
        sys.exit(2)
    return mice[0]


def cmd_dpi(args: argparse.Namespace) -> int:
    dev = _one_mouse(args.device)
    with RazerTransport(dev) as t:
        mouse = RazerMouse(t)
        if args.sub == "get":
            x, y = mouse.get_current_dpi()
            print(f"{dev.spec.name}: current DPI = {x} x {y}")
        elif args.sub == "set":
            y = args.y if args.y is not None else args.x
            mouse.set_current_dpi(args.x, y)
            print(f"{dev.spec.name}: DPI set to {args.x} x {y}")
        elif args.sub == "stages":
            active, stages = mouse.get_dpi_stages()
            print(f"{dev.spec.name}: active stage = {active}, {len(stages)} stored:")
            for s in stages:
                marker = " *" if s.stage == active else "  "
                print(f"  {marker} stage {s.stage}: {s.dpi_x} x {s.dpi_y}")
    return 0


def cmd_poll(args: argparse.Namespace) -> int:
    dev = _one_mouse(args.device)
    with RazerTransport(dev) as t:
        mouse = RazerMouse(t)
        if args.sub == "get":
            hz = mouse.get_polling_rate()
            print(f"{dev.spec.name}: polling rate = {hz} Hz")
        elif args.sub == "set":
            mouse.set_polling_rate(args.hz)
            print(f"{dev.spec.name}: polling rate set to {args.hz} Hz")
    return 0


def cmd_gui(args: argparse.Namespace) -> int:
    from .gui import main as gui_main
    return gui_main()


def cmd_info(args: argparse.Namespace) -> int:
    dev = _one_mouse(args.device)
    with RazerTransport(dev) as t:
        mouse = RazerMouse(t)
        print(f"Device:   {dev.spec.name}")
        print(f"VID/PID:  0x{dev.spec.vid:04x} / 0x{dev.spec.pid:04x}")
        print(f"Firmware: {mouse.get_firmware_version()}")
        print(f"Serial:   {mouse.get_serial()}")
        print(f"Max DPI:  {dev.spec.max_dpi}")
        print(f"Stages:   up to {dev.spec.dpi_stages}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="openrazer-win",
        description="Configure Razer mice on Windows without the vendor software.",
    )
    p.add_argument("--version", action="version", version=f"openrazer-win {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    p_list = sub.add_parser("list", help="List connected Razer devices.")
    p_list.add_argument("--all", action="store_true",
                        help="Show every Razer HID interface, not only known devices.")
    p_list.set_defaults(func=cmd_list)

    p_dpi = sub.add_parser("dpi", help="Read or set mouse DPI.")
    p_dpi.add_argument("--device", help="Match by device name substring or pid.")
    dpi_sub = p_dpi.add_subparsers(dest="sub", required=True)
    dpi_get = dpi_sub.add_parser("get", help="Print current DPI.")
    dpi_set = dpi_sub.add_parser("set", help="Set current DPI (volatile).")
    dpi_set.add_argument("x", type=int, help="X DPI (or both, if Y omitted).")
    dpi_set.add_argument("y", type=int, nargs="?", help="Y DPI (defaults to X).")
    dpi_sub.add_parser("stages", help="Print the stored DPI stage table.")
    p_dpi.set_defaults(func=cmd_dpi)

    p_poll = sub.add_parser("poll", help="Read or set polling rate.")
    p_poll.add_argument("--device", help="Match by device name substring or pid.")
    poll_sub = p_poll.add_subparsers(dest="sub", required=True)
    poll_sub.add_parser("get", help="Print polling rate.")
    poll_set = poll_sub.add_parser("set", help="Set polling rate.")
    poll_set.add_argument("hz", type=int, choices=(125, 500, 1000))
    p_poll.set_defaults(func=cmd_poll)

    p_info = sub.add_parser("info", help="Print device info (firmware, serial, caps).")
    p_info.add_argument("--device", help="Match by device name substring or pid.")
    p_info.set_defaults(func=cmd_info)

    p_gui = sub.add_parser("gui", help="Launch the tkinter GUI.")
    p_gui.set_defaults(func=cmd_gui)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
