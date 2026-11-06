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


@dataclass
class ButtonAction:
    """One button binding as read from the mouse.

    `action_type` values seen empirically on Basilisk V3:
      0x00 = disabled
      0x01 = default mouse function  (payload[0] = mouse button id)
      0x02 = keyboard / HID          (payload[1] = HID keycode)
    """
    profile: int
    button_id: int
    action_type: int
    sub_type: int
    payload: bytes

    @property
    def summary(self) -> str:
        if self.action_type == BTN_ACTION_DEFAULT:
            return f"default mouse btn {self.payload[0]}"
        if self.action_type == BTN_ACTION_KEYBOARD:
            from .hid_keys import hid_name
            code = self.payload[1]
            return f"HID 0x{code:02x} ({hid_name(code)})"
        if self.action_type == BTN_ACTION_DISABLE:
            return "disabled"
        return f"type 0x{self.action_type:02x} payload={self.payload.hex()}"


def _validate_rgb(r: int, g: int, b: int) -> None:
    for name, v in (("r", r), ("g", g), ("b", b)):
        if not 0 <= v <= 255:
            raise ValueError(f"{name} channel {v} outside 0..255")


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

    # ---- Lighting: brightness -----------------------------------------

    # Brightness is addressed per-LED-zone on Basilisk V3, not on LED_ZERO
    # as the fork's fetch of razerchromacommon.c initially suggested. Probe
    # 2026-08-30: LED_ZERO returns FAILURE for brightness get; only the
    # per-zone LED ids (SCROLL_WHEEL, LOGO) return valid data.

    def get_brightness(self, led: int, store: int = NOSTORE) -> int:
        """Read backlight brightness (0..255) for a specific LED zone.

        `led` must be a real zone id — LED_SCROLL_WHEEL, LED_LOGO, etc.
        LED_ZERO is not valid for GET on this device family.
        """
        args = bytes([store, led, 0x00])
        resp = self._send(
            CMD_CLASS_LED, CMD_LED_GET_BRIGHTNESS, data_size=0x03, args=args,
        )
        return resp.arguments[2]

    def set_brightness(self, brightness: int, led: int,
                       store: int = VARSTORE) -> None:
        """Write backlight brightness for one LED zone. Use VARSTORE for
        persistence, NOSTORE for volatile."""
        if not 0 <= brightness <= 255:
            raise ValueError(f"brightness {brightness} outside 0..255")
        args = bytes([store, led, brightness & 0xFF])
        self._send(
            CMD_CLASS_LED, CMD_LED_SET_BRIGHTNESS, data_size=0x03, args=args,
        )

    def get_all_brightness(self) -> dict[int, int]:
        """Convenience: read brightness for every zone the device exposes.
        Returns {LED_id: brightness} for whichever zones respond."""
        result: dict[int, int] = {}
        for led in (LED_SCROLL_WHEEL, LED_LOGO, LED_BACKLIGHT):
            try:
                result[led] = self.get_brightness(led)
            except IOError:
                pass
        return result

    def set_all_brightness(self, brightness: int, store: int = VARSTORE) -> None:
        """Convenience: set every responsive zone to the same brightness."""
        for led in self.get_all_brightness().keys():
            self.set_brightness(brightness, led, store=store)

    # ---- Lighting: effects (class 0x0F extended matrix) ---------------

    def set_effect_none(self, led: int = LED_ZERO, store: int = VARSTORE) -> None:
        """Turn the LEDs off (accepts light being written to but shows none)."""
        args = bytes([store, led, EFFECT_NONE])
        self._send(CMD_CLASS_LED, CMD_LED_SET_EFFECT, data_size=0x06, args=args)

    def set_effect_static(self, r: int, g: int, b: int,
                          led: int = LED_ZERO, store: int = VARSTORE) -> None:
        """Solid colour. RGB each 0..255."""
        _validate_rgb(r, g, b)
        args = bytes([store, led, EFFECT_STATIC, 0x00, 0x00, 0x01, r, g, b])
        self._send(CMD_CLASS_LED, CMD_LED_SET_EFFECT, data_size=0x09, args=args)

    def set_effect_spectrum(self, led: int = LED_ZERO,
                            store: int = VARSTORE) -> None:
        """Full-spectrum colour cycle."""
        args = bytes([store, led, EFFECT_SPECTRUM])
        self._send(CMD_CLASS_LED, CMD_LED_SET_EFFECT, data_size=0x06, args=args)

    def set_effect_wave(self, direction: int = 1, speed: int = 0x28,
                        led: int = LED_ZERO, store: int = VARSTORE) -> None:
        """Colour wave. direction: 1 = left, 2 = right (per OpenRazer). speed 0x28 default."""
        if direction not in (0, 1, 2):
            raise ValueError(f"wave direction must be 0, 1, or 2 (got {direction})")
        args = bytes([store, led, EFFECT_WAVE, direction, speed])
        self._send(CMD_CLASS_LED, CMD_LED_SET_EFFECT, data_size=0x06, args=args)

    def set_effect_breathing_single(self, r: int, g: int, b: int,
                                     led: int = LED_ZERO,
                                     store: int = VARSTORE) -> None:
        """Breathing fade on a single colour. Not wired for BV3 in OpenRazer;
        try-it-and-see per the fork's note."""
        _validate_rgb(r, g, b)
        args = bytes([store, led, EFFECT_BREATHING, 0x01, 0x00, 0x01, r, g, b])
        self._send(CMD_CLASS_LED, CMD_LED_SET_EFFECT, data_size=0x09, args=args)

    def set_effect_reactive(self, r: int, g: int, b: int, speed: int = 0x02,
                            led: int = LED_ZERO, store: int = VARSTORE) -> None:
        """Flash on click. Not wired for BV3 in OpenRazer; try-it-and-see."""
        _validate_rgb(r, g, b)
        if not 1 <= speed <= 4:
            raise ValueError(f"reactive speed must be 1..4 (got {speed})")
        args = bytes([store, led, EFFECT_REACTIVE, 0x00, speed, 0x01, r, g, b])
        self._send(CMD_CLASS_LED, CMD_LED_SET_EFFECT, data_size=0x09, args=args)

    # ---- Lighting: underglow (extended matrix custom frame) -----------

    # BV3's 11-LED underglow strip is a 1x11 matrix addressed via the
    # extended-matrix custom-frame path (class 0x0F / id 0x03) followed
    # by an activate-custom-effect command. Not covered by the LED_ZERO
    # effect writers — those only reach wheel + logo. Per fork's read
    # of razermouse_driver.c and razerchromacommon.c.

    def set_custom_frame(self, row: int, start_col: int, stop_col: int,
                          rgb_data: bytes) -> None:
        """Write a slice of the custom LED framebuffer.

        rgb_data length must be (stop_col - start_col + 1) * 3 bytes:
        R, G, B per LED in column order. Follow with set_effect_custom()
        to activate the frame — the write is buffered until then.
        """
        expected = (stop_col - start_col + 1) * 3
        if len(rgb_data) != expected:
            raise ValueError(
                f"rgb_data must be {expected} bytes for cols {start_col}..{stop_col}, "
                f"got {len(rgb_data)}"
            )
        args = bytearray(80)
        # args[0], args[1] stay 0 per OpenRazer helper defaults
        args[2] = row & 0xFF
        args[3] = start_col & 0xFF
        args[4] = stop_col & 0xFF
        args[5:5 + len(rgb_data)] = rgb_data
        self._send(
            CMD_CLASS_LED, CMD_LED_SET_CUSTOM_FRAME,
            data_size=0x47, args=bytes(args),
        )

    def set_effect_custom(self) -> None:
        """Activate the buffered custom frame. Call after set_custom_frame()."""
        args = bytes([NOSTORE, LED_ZERO, EFFECT_CUSTOM])
        self._send(
            CMD_CLASS_LED, CMD_LED_SET_EFFECT, data_size=0x0C, args=args,
        )

    def set_underglow_static(self, r: int, g: int, b: int,
                              num_leds: int = 11) -> None:
        """Set the underglow strip to a solid colour. Two writes: the
        custom frame with `num_leds` identical RGB triplets, then activate."""
        _validate_rgb(r, g, b)
        rgb = bytes([r, g, b] * num_leds)
        self.set_custom_frame(row=0, start_col=0, stop_col=num_leds - 1, rgb_data=rgb)
        self.set_effect_custom()

    def set_underglow_off(self, num_leds: int = 11) -> None:
        """Blank the underglow strip (all LEDs 0,0,0) via custom frame."""
        self.set_underglow_static(0, 0, 0, num_leds=num_leds)

    # ---- Buttons (class 0x02) — empirically decoded on Basilisk V3 ----

    def get_button_action(self, button_id: int, profile: int = 0) -> "ButtonAction":
        """Read what physical button `button_id` is bound to in `profile`."""
        args = bytes([profile & 0xFF, button_id & 0xFF])
        resp = self._send(
            CMD_CLASS_BUTTON, CMD_BUTTON_GET_MAPPING, data_size=0x02, args=args,
        )
        # Response layout (empirical, BV3):
        #   arg[0]=profile arg[1]=button_id arg[2]=00
        #   arg[3]=action_type arg[4]=sub_type arg[5..]=code bytes
        action_type = resp.arguments[3]
        sub_type = resp.arguments[4]
        # Sub_type is where the meaningful payload starts. For type=0x01 (default)
        # the code is arg[5] (mouse button id). For type=0x02 (keyboard) the code
        # is arg[6] (HID keycode). Store both raw payload bytes for callers who
        # want the full detail without a per-type decoder here.
        payload = bytes(resp.arguments[5:9])
        return ButtonAction(
            profile=profile, button_id=button_id,
            action_type=action_type, sub_type=sub_type, payload=payload,
        )

    def set_button_action(self, button_id: int, action_type: int,
                          payload: bytes, sub_type: int = 0x00,
                          profile: int = 0) -> None:
        """Write a button binding. `payload` is the type-specific data
        (mouse button id for type=0x01, HID keycode for type=0x02, etc.)."""
        args = bytearray(80)
        args[0] = profile & 0xFF
        args[1] = button_id & 0xFF
        args[2] = 0x00
        args[3] = action_type & 0xFF
        args[4] = sub_type & 0xFF
        for i, b in enumerate(payload[:75]):
            args[5 + i] = b
        # data_size for a keyboard remap is 0x08 empirically; a default binding
        # is 0x06. Use max seen (0x0A) so we don't chop off longer action payloads.
        self._send(
            CMD_CLASS_BUTTON, CMD_BUTTON_SET_MAPPING, data_size=0x0A, args=bytes(args),
        )

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
