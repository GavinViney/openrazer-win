"""USB HID Keyboard Usage IDs ↔ Windows Virtual Key codes ↔ display names.

The mouse firmware stores keyboard bindings as HID Usage IDs (HID Usage Tables
v1.12, Keyboard page 0x07). Windows reports keystrokes as Virtual Key codes
(VK_*, see winuser.h). The two are not the same — e.g. 'F' is HID 0x09 but
VK 0x46. Any capture-from-live-keypress flow MUST translate.

Covers the common set: letters, digits, function keys, arrows, modifiers,
whitespace and the main editing keys. Not exhaustive — numpad and media keys
can be added when needed.
"""
from __future__ import annotations

# HID Usage ID (byte) → human-readable name.
HID_NAMES: dict[int, str] = {
    # Letters
    0x04: "A", 0x05: "B", 0x06: "C", 0x07: "D", 0x08: "E", 0x09: "F",
    0x0A: "G", 0x0B: "H", 0x0C: "I", 0x0D: "J", 0x0E: "K", 0x0F: "L",
    0x10: "M", 0x11: "N", 0x12: "O", 0x13: "P", 0x14: "Q", 0x15: "R",
    0x16: "S", 0x17: "T", 0x18: "U", 0x19: "V", 0x1A: "W", 0x1B: "X",
    0x1C: "Y", 0x1D: "Z",
    # Digits (top row)
    0x1E: "1", 0x1F: "2", 0x20: "3", 0x21: "4", 0x22: "5",
    0x23: "6", 0x24: "7", 0x25: "8", 0x26: "9", 0x27: "0",
    # Whitespace / editing
    0x28: "Enter", 0x29: "Esc", 0x2A: "Backspace", 0x2B: "Tab", 0x2C: "Space",
    0x2D: "- _", 0x2E: "= +", 0x2F: "[ {", 0x30: "] }", 0x31: "\\ |",
    0x33: "; :", 0x34: "' \"", 0x35: "` ~", 0x36: ", <", 0x37: ". >", 0x38: "/ ?",
    0x39: "CapsLock",
    # Function keys
    0x3A: "F1", 0x3B: "F2", 0x3C: "F3", 0x3D: "F4", 0x3E: "F5", 0x3F: "F6",
    0x40: "F7", 0x41: "F8", 0x42: "F9", 0x43: "F10", 0x44: "F11", 0x45: "F12",
    # Nav cluster
    0x46: "PrtScr", 0x47: "ScrollLock", 0x48: "Pause",
    0x49: "Insert", 0x4A: "Home", 0x4B: "PageUp",
    0x4C: "Delete", 0x4D: "End", 0x4E: "PageDown",
    0x4F: "Right", 0x50: "Left", 0x51: "Down", 0x52: "Up",
    # Modifiers (left side; right side at 0xE4-0xE7)
    0xE0: "LCtrl", 0xE1: "LShift", 0xE2: "LAlt", 0xE3: "LWin",
    0xE4: "RCtrl", 0xE5: "RShift", 0xE6: "RAlt", 0xE7: "RWin",
}

# Windows Virtual Key code → HID Usage ID. Lets a live keypress captured through
# Tk (which reports event.keycode as the Win VK) be translated to what the mouse
# firmware actually stores.
VK_TO_HID: dict[int, int] = {
    # Letters (VK is uppercase ASCII)
    **{0x41 + i: 0x04 + i for i in range(26)},  # A-Z → 0x04-0x1D
    # Digits top row (VK is ASCII '0'-'9'; HID runs 1,2,3,4,5,6,7,8,9,0)
    0x31: 0x1E, 0x32: 0x1F, 0x33: 0x20, 0x34: 0x21, 0x35: 0x22,
    0x36: 0x23, 0x37: 0x24, 0x38: 0x25, 0x39: 0x26, 0x30: 0x27,
    # Whitespace / editing
    0x0D: 0x28,  # VK_RETURN
    0x1B: 0x29,  # VK_ESCAPE
    0x08: 0x2A,  # VK_BACK
    0x09: 0x2B,  # VK_TAB
    0x20: 0x2C,  # VK_SPACE
    0xBD: 0x2D,  # VK_OEM_MINUS   -
    0xBB: 0x2E,  # VK_OEM_PLUS    =
    0xDB: 0x2F,  # VK_OEM_4       [
    0xDD: 0x30,  # VK_OEM_6       ]
    0xDC: 0x31,  # VK_OEM_5       \
    0xBA: 0x33,  # VK_OEM_1       ;
    0xDE: 0x34,  # VK_OEM_7       '
    0xC0: 0x35,  # VK_OEM_3       `
    0xBC: 0x36,  # VK_OEM_COMMA   ,
    0xBE: 0x37,  # VK_OEM_PERIOD  .
    0xBF: 0x38,  # VK_OEM_2       /
    0x14: 0x39,  # VK_CAPITAL
    # Function keys (VK_F1 = 0x70, HID 0x3A)
    **{0x70 + i: 0x3A + i for i in range(12)},
    # Nav cluster
    0x2C: 0x46,  # VK_SNAPSHOT (PrtScr)
    0x91: 0x47,  # VK_SCROLL
    0x13: 0x48,  # VK_PAUSE
    0x2D: 0x49,  # VK_INSERT
    0x24: 0x4A,  # VK_HOME
    0x21: 0x4B,  # VK_PRIOR  (PageUp)
    0x2E: 0x4C,  # VK_DELETE
    0x23: 0x4D,  # VK_END
    0x22: 0x4E,  # VK_NEXT   (PageDown)
    0x27: 0x4F,  # VK_RIGHT
    0x25: 0x50,  # VK_LEFT
    0x28: 0x51,  # VK_DOWN
    0x26: 0x52,  # VK_UP
    # Modifiers — Tk collapses left/right in some cases; mapping both.
    0xA0: 0xE1,  # VK_LSHIFT
    0xA1: 0xE5,  # VK_RSHIFT
    0x10: 0xE1,  # VK_SHIFT (generic → LShift)
    0xA2: 0xE0,  # VK_LCONTROL
    0xA3: 0xE4,  # VK_RCONTROL
    0x11: 0xE0,  # VK_CONTROL (generic → LCtrl)
    0xA4: 0xE2,  # VK_LMENU (LAlt)
    0xA5: 0xE6,  # VK_RMENU (RAlt)
    0x12: 0xE2,  # VK_MENU (generic → LAlt)
    0x5B: 0xE3,  # VK_LWIN
    0x5C: 0xE7,  # VK_RWIN
}


def hid_name(code: int) -> str:
    """Return the key name for an HID Usage ID, or a hex fallback."""
    return HID_NAMES.get(code, f"0x{code:02x}")


def vk_to_hid(vk: int) -> int | None:
    """Translate a Windows Virtual Key code to its HID Usage ID, or None if
    the key isn't in our table. Callers should warn the user rather than
    silently writing an unknown value."""
    return VK_TO_HID.get(vk)
