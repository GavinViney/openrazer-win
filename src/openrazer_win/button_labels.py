"""Per-device button labels (user-readable names for each Razer button ID).

Labels are stored per device key (vendor+product+serial) so swapping to a
different mouse doesn't mix up its button numbering. Bootstrapped by pressing
each physical button and typing what it is — openrazer-win can't infer this
from the protocol because keyboard-bound buttons emit the KEY they're bound
to, not their id.
"""
from __future__ import annotations

import json
import os
from pathlib import Path


def _store_path() -> Path:
    appdata = Path(os.environ.get("APPDATA", str(Path.home() / ".config")))
    return appdata / "openrazer-win" / "button_labels.json"


def _device_key(device) -> str:
    """Build a stable key for a DiscoveredDevice. Uses spec.name + serial if
    available; falls back to (vid, pid)."""
    spec = device.spec
    serial = getattr(device, "serial", None) or ""
    base = f"{spec.name}"
    if serial:
        base += f":{serial[-6:]}"
    else:
        base += f":{spec.vid:04x}{spec.pid:04x}"
    return base


def load_all() -> dict:
    p = _store_path()
    if not p.is_file():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def load_for(device) -> dict[int, str]:
    """Return {button_id: label} for this device, or an empty dict."""
    raw = load_all().get(_device_key(device), {})
    out: dict[int, str] = {}
    for k, v in raw.items():
        try:
            out[int(k)] = str(v)
        except (TypeError, ValueError):
            pass
    return out


def save_for(device, labels: dict[int, str]) -> None:
    all_ = load_all()
    all_[_device_key(device)] = {str(k): v for k, v in labels.items() if v.strip()}
    p = _store_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(all_, indent=2), encoding="utf-8")
