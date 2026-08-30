"""Known Razer devices and their capabilities.

USB IDs and per-model quirks are ported from OpenRazer (razerkbd_driver.c,
razermouse_driver.c) and libratbag (data/*.device). Only mice are listed
here — Phase 1 scope. Others will land as they are needed.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

RAZER_VENDOR_ID = 0x1532


class DeviceKind(str, Enum):
    MOUSE = "mouse"
    KEYBOARD = "keyboard"
    MOUSEPAD = "mousepad"


@dataclass(frozen=True)
class DeviceSpec:
    vid: int
    pid: int
    name: str
    kind: DeviceKind
    max_dpi: int
    dpi_stages: int
    transaction_id: int = 0x1F
    """Some Razer devices require a specific transaction ID for config reports.
    0x1F is the modern default used by most current-gen mice."""


KNOWN_DEVICES: tuple[DeviceSpec, ...] = (
    # Basilisk V3 (wired) — Gavin's test rig
    DeviceSpec(
        vid=RAZER_VENDOR_ID,
        pid=0x0099,
        name="Razer Basilisk V3",
        kind=DeviceKind.MOUSE,
        max_dpi=26000,
        dpi_stages=5,
        transaction_id=0x1F,
    ),
    # DeathAdder V2 — common enough to be worth adding early
    DeviceSpec(
        vid=RAZER_VENDOR_ID,
        pid=0x0084,
        name="Razer DeathAdder V2",
        kind=DeviceKind.MOUSE,
        max_dpi=20000,
        dpi_stages=5,
        transaction_id=0x1F,
    ),
    # Viper Mini — common competitive mouse
    DeviceSpec(
        vid=RAZER_VENDOR_ID,
        pid=0x008A,
        name="Razer Viper Mini",
        kind=DeviceKind.MOUSE,
        max_dpi=8500,
        dpi_stages=5,
        transaction_id=0x1F,
    ),
)


def find_spec(vid: int, pid: int) -> DeviceSpec | None:
    for spec in KNOWN_DEVICES:
        if spec.vid == vid and spec.pid == pid:
            return spec
    return None
