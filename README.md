# openrazer-win

A minimal, focused Windows utility for configuring Razer mice without the vendor software.

Read and write DPI stages, polling rate, button remapping, per-zone brightness, and per-LED lighting (including the underglow strip) on Razer mice through the HID configuration protocol that [OpenRazer](https://openrazer.github.io/) and [libratbag](https://github.com/libratbag/libratbag) already speak on Linux. Ported to Python + [hidapi](https://github.com/trezor/cython-hidapi) so it runs on Windows without any vendor stack installed.

Backstory: [The Overhead We Won't Reinstall](https://www.indigo-nx.com/journal/the-overhead-we-wont-reinstall-2026-08-30).

## Status

Working end-to-end on the Razer Basilisk V3 as the first supported device. All read paths verified against a live device; all write paths verified against a live device except `set_dpi_stages` (the SET id is kept at OpenRazer's documented value pending an actual write test).

Package is installable from source; no PyInstaller-built .exe or PyPI release yet.

## What works today

- **DPI** — read current XY, write current XY (volatile), read the full 5-stage table.
- **Polling rate** — read + write (125 / 500 / 1000 Hz).
- **Buttons** — read every populated physical button's binding, write remaps (default mouse function / keyboard HID key / disable). Empirically decoded — OpenRazer does not document this.
- **Lighting** — per-zone brightness (scroll wheel + logo), effects (none / static / spectrum / wave) via the extended matrix, and **per-LED colour control on the underglow strip** via the custom-frame path.
- **Profiles** — save the mouse's current state to a named JSON profile, apply it later.
- **CLI** — `list`, `info`, `dpi get/set/stages`, `poll get/set`.
- **GUI** — one tkinter window with device stats, all controls, per-LED colour grid, and a Toplevel button tester with a live event log.

## Device compatibility

| Device | VID:PID | Kind | Verified today | Notes |
|--------|---------|------|----------------|-------|
| Razer Basilisk V3 | 1532:0099 | Mouse | ✅ reads + writes | Reference device; DPI, polling, buttons, brightness, effects, per-LED underglow all working |
| Razer DeathAdder V2 | 1532:0084 | Mouse | ⚠ declared | Present in `KNOWN_DEVICES`; not physically tested |
| Razer Viper Mini | 1532:008A | Mouse | ⚠ declared | Present in `KNOWN_DEVICES`; not physically tested |

Other Razer devices should work with only a `DeviceSpec` entry added — the transport auto-probes each HID path for the config surface rather than hardcoding an interface. If you have a Razer mouse not in the list, `openrazer-win list --all` will show every Razer HID interface on the system; open a PR with the VID/PID and the results of a probe run.

## Install (from source, dev)

```powershell
git clone https://github.com/GavinViney/openrazer-win.git
cd openrazer-win
pip install -e .
openrazer-win list
openrazer-win gui
```

Requires Python 3.10+ and Windows.

## Scope

- **In:** DPI, polling, buttons, lighting (per-zone brightness, effects, per-LED underglow), JSON profiles. CLI + GUI.
- **On roadmap:** More devices as physical test rigs land. Per-app profile switching. Directional-hit feedback via the underglow strip as a game-integration primitive (one LED per direction, driven by game state — nothing else on the market seems to do this today).
- **Not in scope for v1:** kernel driver anything, process injection, macro-recording UI (config file only), cloud accounts, telemetry.

## Credits

Protocol knowledge is a direct port of the work done by:

- **OpenRazer** — the Linux kernel driver suite and userspace daemon that documented most of the Razer HID configuration protocol.
- **libratbag / ratbagd** — the higher-level Linux abstraction over gaming mice.
- **OpenRGB** — the cross-platform lighting project that already speaks Razer Chroma on Windows via the same protocol.

The button-remapping command layout was decoded empirically against a live Basilisk V3 in this project — OpenRazer does not document that path, and libratbag has no Razer driver. That decoding is now in `src/openrazer_win/mouse.py` for anyone else who needs it.

## License

GPLv3. Full text in `COPYING`. Same spirit as the ecosystem the protocol knowledge came from.
