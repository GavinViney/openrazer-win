"""HID transport for Razer feature reports.

Razer devices expose several HID interfaces on Windows. The one that
accepts configuration feature reports is not always the same across
device families — the Basilisk V3, for instance, routes them through
interface 3 with a Consumer (0x000c) usage page rather than the
vendor-defined usage page that OpenRazer's Linux hidraw path uses.

Rather than hardcode per-device interface numbers we assumed wrong,
`discover()` probes each candidate HID path with a no-side-effect
command (get firmware version) and only reports devices where at
least one path round-trips a valid Razer response.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import hid

from .devices import DeviceSpec, find_spec, RAZER_VENDOR_ID
from .protocol import REPORT_ID, REPORT_LEN, RazerReport


@dataclass
class DiscoveredDevice:
    spec: DeviceSpec
    path: bytes
    interface_number: int
    usage_page: int
    manufacturer: str
    product: str
    serial: str


# --- Enumeration ---------------------------------------------------------


def enumerate_all_razer() -> list[dict]:
    """Diagnostic: raw dump of every Razer HID interface, known or not."""
    return list(hid.enumerate(RAZER_VENDOR_ID, 0))


def discover(probe: bool = True) -> list[DiscoveredDevice]:
    """Enumerate connected Razer devices we know how to talk to.

    If `probe` is True (default), each candidate HID path is tested with
    a get-firmware command and only paths that round-trip a valid
    response are returned — so the caller gets an already-working handle.
    """
    candidates: dict[tuple[int, int], list[DiscoveredDevice]] = {}
    for info in hid.enumerate(RAZER_VENDOR_ID, 0):
        spec = find_spec(info["vendor_id"], info["product_id"])
        if spec is None:
            continue
        key = (spec.vid, spec.pid)
        candidates.setdefault(key, []).append(
            DiscoveredDevice(
                spec=spec,
                path=info["path"],
                interface_number=info.get("interface_number", -1),
                usage_page=info.get("usage_page", 0),
                manufacturer=info.get("manufacturer_string") or "",
                product=info.get("product_string") or "",
                serial=info.get("serial_number") or "",
            )
        )

    if not probe:
        # Return one path per device, unfiltered — mainly for CLI list --known.
        return [entries[0] for entries in candidates.values()]

    working: list[DiscoveredDevice] = []
    for entries in candidates.values():
        found = _probe_first_working(entries)
        if found is not None:
            working.append(found)
    return working


def _probe_first_working(entries: list[DiscoveredDevice]) -> DiscoveredDevice | None:
    """Try each entry with a get-firmware request; return the first that responds."""
    req = RazerReport(
        command_class=0x00,
        command_id=0x81,
        data_size=0x02,
        transaction_id=entries[0].spec.transaction_id,
    )
    for entry in entries:
        try:
            with RazerTransport(entry) as t:
                resp = t.send(req)
                if resp.ok:
                    return entry
        except Exception:
            continue
    return None


# --- Transport -----------------------------------------------------------


class RazerTransport:
    """Send a Razer feature report and read back the response."""

    RESPONSE_POLL_INTERVAL = 0.005  # seconds
    RESPONSE_TIMEOUT = 1.0

    def __init__(self, device: DiscoveredDevice):
        self.device = device
        self._dev = hid.device()
        self._dev.open_path(device.path)

    def close(self) -> None:
        try:
            self._dev.close()
        except Exception:
            pass

    def __enter__(self) -> "RazerTransport":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def send(self, report: RazerReport) -> RazerReport:
        """Write the given RazerReport, poll for the response, return it."""
        payload = bytes([REPORT_ID]) + report.pack()
        self._dev.send_feature_report(payload)

        deadline = time.monotonic() + self.RESPONSE_TIMEOUT
        while time.monotonic() < deadline:
            time.sleep(self.RESPONSE_POLL_INTERVAL)
            try:
                raw = bytes(self._dev.get_feature_report(REPORT_ID, REPORT_LEN + 1))
            except OSError:
                continue
            if len(raw) == REPORT_LEN + 1:
                raw = raw[1:]  # strip the leading report ID hidapi may return
            if len(raw) != REPORT_LEN:
                continue
            try:
                resp = RazerReport.unpack(raw)
            except ValueError:
                continue
            if resp.command_class == report.command_class and resp.command_id == report.command_id:
                return resp
        raise TimeoutError(
            f"no response for command class=0x{report.command_class:02x} "
            f"id=0x{report.command_id:02x} within {self.RESPONSE_TIMEOUT}s"
        )
