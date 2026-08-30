"""High-level mouse operations built on top of the Razer HID protocol.

Command classes and IDs are ported from OpenRazer's razer_common.h and
razermouse_driver.c.
"""

from __future__ import annotations

from dataclasses import dataclass

from .protocol import RazerReport, Status
from .transport import RazerTransport


# Command class / id constants
CMD_CLASS_MOUSE = 0x04
CMD_CLASS_STANDARD = 0x00

CMD_GET_FIRMWARE = 0x81           # class 0x00
CMD_GET_SERIAL = 0x82             # class 0x00

CMD_MOUSE_SET_DPI_XY = 0x05       # class 0x04
CMD_MOUSE_GET_DPI_XY = 0x85       # class 0x04
CMD_MOUSE_SET_DPI_STAGES = 0x06   # class 0x04 — OpenRazer-documented (SET side unverified on BV3)
CMD_MOUSE_GET_DPI_STAGES = 0x83   # class 0x04 — Basilisk V3 empirical: 0x83 returns full 5-stage table; 0x86 returns only the active stage
CMD_MOUSE_SET_POLL_RATE = 0x05    # class 0x00 (yes, shares an id with mouse cmds — different class)
CMD_MOUSE_GET_POLL_RATE = 0x85    # class 0x00

# Button remapping (class 0x02) — empirically decoded on Basilisk V3
CMD_BUTTON_SET_MAPPING = 0x0C
CMD_BUTTON_GET_MAPPING = 0x8C

# Lighting (class 0x0F extended matrix) — per OpenRazer razerchromacommon.c
CMD_LED_SET_EFFECT = 0x02         # class 0x0F
CMD_LED_SET_CUSTOM_FRAME = 0x03   # class 0x0F
CMD_LED_SET_BRIGHTNESS = 0x04     # class 0x0F
CMD_LED_GET_BRIGHTNESS = 0x84     # class 0x0F

CMD_CLASS_BUTTON = 0x02
CMD_CLASS_LED = 0x0F

# LED zone constants (from razercommon.h)
LED_ZERO = 0x00
LED_SCROLL_WHEEL = 0x01
LED_LOGO = 0x04
LED_BACKLIGHT = 0x05

# Storage modes
NOSTORE = 0x00
VARSTORE = 0x01

# Lighting effect ids (arg[2] of class 0x0F id 0x02, Basilisk V3 wired)
EFFECT_NONE = 0x00
EFFECT_STATIC = 0x01
EFFECT_BREATHING = 0x02
EFFECT_SPECTRUM = 0x03
EFFECT_WAVE = 0x04
EFFECT_REACTIVE = 0x05
EFFECT_STARLIGHT = 0x07
EFFECT_CUSTOM = 0x08

# Button action types (empirically decoded on Basilisk V3)
BTN_ACTION_DEFAULT = 0x01   # default mouse function
BTN_ACTION_KEYBOARD = 0x02  # keyboard/HID key (payload: HID keycode)
BTN_ACTION_DISABLE = 0x00   # button disabled


POLL_RATE_1000 = 0x01
POLL_RATE_500 = 0x02
POLL_RATE_125 = 0x08
POLL_RATE_VALUES = {1000: POLL_RATE_1000, 500: POLL_RATE_500, 125: POLL_RATE_125}
POLL_RATE_NAMES = {v: k for k, v in POLL_RATE_VALUES.items()}


@dataclass
class DPIStage:
    stage: int  # 1-based
    dpi_x: int
    dpi_y: int


class RazerMouse:
    """High-level operations for one connected Razer mouse."""

    def __init__(self, transport: RazerTransport):
        self.t = transport
        self.spec = transport.device.spec

    # ---- DPI: current stage read/write ---------------------------------

    def get_current_dpi(self) -> tuple[int, int]:
        """Read the mouse's current DPI (x, y). Not the stage table — the value
        the sensor is using right now."""
        resp = self._send(CMD_CLASS_MOUSE, CMD_MOUSE_GET_DPI_XY, data_size=0x07)
        x = (resp.arguments[1] << 8) | resp.arguments[2]
        y = (resp.arguments[3] << 8) | resp.arguments[4]
        return x, y

    def set_current_dpi(self, x: int, y: int) -> None:
        """Write the sensor's active DPI immediately (independent of stages)."""
        self._validate_dpi(x)
        self._validate_dpi(y)
        args = bytes([
            0x00,               # variable store: 0x00 = volatile, 0x01 = flash
            (x >> 8) & 0xFF,
            x & 0xFF,
            (y >> 8) & 0xFF,
            y & 0xFF,
        ])
        self._send(CMD_CLASS_MOUSE, CMD_MOUSE_SET_DPI_XY, data_size=0x07, args=args)

    # ---- DPI stages ----------------------------------------------------

    def get_dpi_stages(self) -> tuple[int, list[DPIStage]]:
        """Return (active_stage, [DPIStage, ...]) for the stored stage table."""
        resp = self._send(
            CMD_CLASS_MOUSE, CMD_MOUSE_GET_DPI_STAGES, data_size=0x26,
        )
        active = resp.arguments[1]
        count = resp.arguments[2]
        stages: list[DPIStage] = []
        # Each stage is 7 bytes: stage#, x_hi, x_lo, y_hi, y_lo, reserved x2
        for i in range(count):
            base = 3 + i * 7
            stage_num = resp.arguments[base]
            x = (resp.arguments[base + 1] << 8) | resp.arguments[base + 2]
            y = (resp.arguments[base + 3] << 8) | resp.arguments[base + 4]
            stages.append(DPIStage(stage=stage_num, dpi_x=x, dpi_y=y))
        return active, stages

    def set_dpi_stages(self, active: int, stages: list[DPIStage]) -> None:
        if not 1 <= active <= len(stages):
            raise ValueError(f"active stage {active} outside 1..{len(stages)}")
        if len(stages) > self.spec.dpi_stages:
            raise ValueError(f"{len(stages)} stages > device max {self.spec.dpi_stages}")
        for s in stages:
            self._validate_dpi(s.dpi_x)
            self._validate_dpi(s.dpi_y)

        args = bytearray(80)
        args[0] = 0x01                # variable store: 0x01 = flash
        args[1] = active & 0xFF
        args[2] = len(stages) & 0xFF
        for i, s in enumerate(stages):
            base = 3 + i * 7
            args[base] = s.stage & 0xFF
            args[base + 1] = (s.dpi_x >> 8) & 0xFF
            args[base + 2] = s.dpi_x & 0xFF
            args[base + 3] = (s.dpi_y >> 8) & 0xFF
            args[base + 4] = s.dpi_y & 0xFF
            # base+5, base+6 stay 0
        self._send(
            CMD_CLASS_MOUSE, CMD_MOUSE_SET_DPI_STAGES, data_size=0x26, args=bytes(args),
        )

    # ---- Polling rate --------------------------------------------------

    def get_polling_rate(self) -> int:
        resp = self._send(CMD_CLASS_STANDARD, CMD_MOUSE_GET_POLL_RATE, data_size=0x01)
        code = resp.arguments[0]
        return POLL_RATE_NAMES.get(code, 0)

    def set_polling_rate(self, hz: int) -> None:
        if hz not in POLL_RATE_VALUES:
            raise ValueError(f"unsupported polling rate {hz}, choose from {list(POLL_RATE_VALUES)}")
        args = bytes([POLL_RATE_VALUES[hz]])
        self._send(CMD_CLASS_STANDARD, CMD_MOUSE_SET_POLL_RATE, data_size=0x01, args=args)

    # ---- Firmware / serial --------------------------------------------

    def get_firmware_version(self) -> str:
        resp = self._send(CMD_CLASS_STANDARD, CMD_GET_FIRMWARE, data_size=0x02)
        return f"v{resp.arguments[0]}.{resp.arguments[1]}"

    def get_serial(self) -> str:
        resp = self._send(CMD_CLASS_STANDARD, CMD_GET_SERIAL, data_size=0x16)
        raw = resp.arguments[:22]
        return raw.rstrip(b"\x00").decode("ascii", errors="replace")

    # ---- internals -----------------------------------------------------

    def _send(
        self,
        cmd_class: int,
        cmd_id: int,
        data_size: int,
        args: bytes = b"",
    ) -> RazerReport:
        req = RazerReport(
            command_class=cmd_class,
            command_id=cmd_id,
            data_size=data_size,
            arguments=args,
            transaction_id=self.spec.transaction_id,
        )
        resp = self.t.send(req)
        if resp.status not in (Status.NEW, Status.SUCCESS):
            raise IOError(
                f"device returned status 0x{resp.status:02x} for "
                f"class=0x{cmd_class:02x} id=0x{cmd_id:02x}"
            )
        return resp

    def _validate_dpi(self, value: int) -> None:
        if not 100 <= value <= self.spec.max_dpi:
            raise ValueError(
                f"dpi {value} outside 100..{self.spec.max_dpi} for {self.spec.name}"
            )
