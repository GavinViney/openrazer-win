# openrazer-win

A minimal, focused Windows utility for configuring Razer mice without the vendor software.

Change DPI stages, polling rate, and other firmware-writable settings on Razer mice through the HID configuration protocol that [OpenRazer](https://openrazer.github.io/) and [libratbag](https://github.com/libratbag/libratbag) already speak on Linux. Ported to Python + [hidapi](https://github.com/trezor/cython-hidapi) so it runs on Windows without any vendor stack installed.

Backstory: [The Overhead We Won't Reinstall](https://www.indigo-nx.com/journal/the-overhead-we-wont-reinstall-2026-08-30).

## Status

**Phase 1 — in build.** DPI + polling for the Razer Basilisk V3 as the first supported device (the test rig here). Other Razer mice will land once the protocol layer is stable — the command set is largely shared across the range.

Not yet installable. First working DPI write to a mouse will be the first tagged release.

## Scope

- **In:** DPI stages (read/write), current DPI stage, polling rate. CLI-first. Single-.exe distribution via PyInstaller.
- **Out (v1):** RGB / Chroma effects — [OpenRGB](https://openrgb.org/) already covers this on Windows using the same reverse-engineered protocol. No reason to duplicate.
- **Out (v1):** Button remapping — Razer stores button maps at the software layer, not in mouse firmware, so FOSS parity requires a Windows input hook (Interception or raw input). That is a separate project.

## Credits

Protocol knowledge is a direct port of the work done by:

- **OpenRazer** — the Linux kernel driver suite and userspace daemon that documented most of the Razer HID configuration protocol.
- **libratbag / ratbagd** — the higher-level Linux abstraction over gaming mice, including Razer.
- **OpenRGB** — the cross-platform lighting project that already speaks Razer Chroma on Windows via the same protocol.

## License

GPLv3. Same spirit as the ecosystem the protocol knowledge came from.
