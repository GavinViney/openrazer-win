"""Razer HID feature-report protocol.

Ported from OpenRazer (driver/razermouse_driver.c) and libratbag
(src/driver-hidpp20/razer.c). Razer devices accept a 90-byte HID
feature report on report ID 0x00 with the following layout:

    byte  0     status
    byte  1     transaction id
    byte  2-3   remaining packets (big-endian)
    byte  4     protocol type (0x00)
    byte  5     data size
    byte  6     command class
    byte  7     command id
    byte  8-87  arguments (80 bytes)
    byte  88    checksum (xor of bytes 2..87)
    byte  89    reserved (0x00)

Status values in a response:
    0x00 new command
    0x01 device busy
    0x02 successful
    0x03 failure
    0x04 timeout
    0x05 not supported
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum


REPORT_ID = 0x00
REPORT_LEN = 90


class Status(IntEnum):
    NEW = 0x00
    BUSY = 0x01
    SUCCESS = 0x02
    FAILURE = 0x03
    TIMEOUT = 0x04
    UNSUPPORTED = 0x05


@dataclass
class RazerReport:
    """One 90-byte Razer HID feature report, in either direction."""

    command_class: int
    command_id: int
    data_size: int
    arguments: bytes = field(default_factory=lambda: b"\x00" * 80)
    status: int = 0x00
    transaction_id: int = 0xFF
    remaining_packets: int = 0x0000
    protocol_type: int = 0x00

    def __post_init__(self) -> None:
        if len(self.arguments) < 80:
            self.arguments = self.arguments + b"\x00" * (80 - len(self.arguments))
        elif len(self.arguments) > 80:
            raise ValueError(f"arguments too long: {len(self.arguments)} > 80")

    def pack(self) -> bytes:
        """Serialise to the 90-byte wire form. Report ID is NOT included here;
        the transport prepends it when calling hidapi's send_feature_report."""
        buf = bytearray(REPORT_LEN)
        buf[0] = self.status & 0xFF
        buf[1] = self.transaction_id & 0xFF
        buf[2] = (self.remaining_packets >> 8) & 0xFF
        buf[3] = self.remaining_packets & 0xFF
        buf[4] = self.protocol_type & 0xFF
        buf[5] = self.data_size & 0xFF
        buf[6] = self.command_class & 0xFF
        buf[7] = self.command_id & 0xFF
        buf[8:88] = self.arguments
        buf[88] = _checksum(buf)
        buf[89] = 0x00
        return bytes(buf)

    @classmethod
    def unpack(cls, data: bytes) -> "RazerReport":
        """Parse a 90-byte wire response back into a RazerReport."""
        if len(data) != REPORT_LEN:
            raise ValueError(f"expected {REPORT_LEN} bytes, got {len(data)}")
        got = data[88]
        want = _checksum(data)
        if got != want:
            raise ValueError(f"checksum mismatch: got 0x{got:02x} want 0x{want:02x}")
        return cls(
            status=data[0],
            transaction_id=data[1],
            remaining_packets=(data[2] << 8) | data[3],
            protocol_type=data[4],
            data_size=data[5],
            command_class=data[6],
            command_id=data[7],
            arguments=bytes(data[8:88]),
        )

    @property
    def ok(self) -> bool:
        return self.status == Status.SUCCESS


def _checksum(buf: bytes | bytearray) -> int:
    """XOR of bytes 2..87 inclusive. Applied to both send and receive."""
    c = 0
    for b in buf[2:88]:
        c ^= b
    return c & 0xFF
