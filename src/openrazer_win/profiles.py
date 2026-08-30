"""Profile system — save + load named sets of mouse settings.

A profile captures: DPI stage table, active stage, polling rate. Bound
to a device (VID/PID) so applying the wrong device's profile is
prevented at load time.

Storage: one JSON file per profile store, in %APPDATA%\\openrazer-win\\
by default. The file is human-readable so power users can edit it
directly if they want.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .mouse import DPIStage, RazerMouse


PROFILE_STORE_FILENAME = "profiles.json"


def default_profile_dir() -> Path:
    base = os.environ.get("APPDATA")
    if base:
        return Path(base) / "openrazer-win"
    return Path.home() / ".openrazer-win"


@dataclass
class Profile:
    name: str
    vid: int
    pid: int
    dpi_stages: list[DPIStage]
    active_stage: int
    polling_rate: int

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "vid": self.vid,
            "pid": self.pid,
            "polling_rate": self.polling_rate,
            "active_stage": self.active_stage,
            "dpi_stages": [asdict(s) for s in self.dpi_stages],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Profile":
        return cls(
            name=data["name"],
            vid=int(data["vid"]),
            pid=int(data["pid"]),
            polling_rate=int(data["polling_rate"]),
            active_stage=int(data["active_stage"]),
            dpi_stages=[DPIStage(**s) for s in data["dpi_stages"]],
        )

    @classmethod
    def capture(cls, name: str, mouse: RazerMouse) -> "Profile":
        """Snapshot the mouse's current settings into a named profile."""
        active, stages = mouse.get_dpi_stages()
        return cls(
            name=name,
            vid=mouse.spec.vid,
            pid=mouse.spec.pid,
            dpi_stages=stages,
            active_stage=active,
            polling_rate=mouse.get_polling_rate(),
        )

    def apply(self, mouse: RazerMouse) -> None:
        """Write this profile's settings to the mouse."""
        if mouse.spec.vid != self.vid or mouse.spec.pid != self.pid:
            raise ValueError(
                f"profile is for 0x{self.vid:04x}/0x{self.pid:04x}, "
                f"mouse is 0x{mouse.spec.vid:04x}/0x{mouse.spec.pid:04x}"
            )
        mouse.set_dpi_stages(self.active_stage, self.dpi_stages)
        mouse.set_polling_rate(self.polling_rate)


@dataclass
class ProfileStore:
    """JSON-backed store for named profiles. Loads on init, saves on write."""

    path: Path
    profiles: dict[str, Profile] = field(default_factory=dict)

    @classmethod
    def open(cls, path: Path | None = None) -> "ProfileStore":
        target = path or (default_profile_dir() / PROFILE_STORE_FILENAME)
        store = cls(path=target)
        store.reload()
        return store

    def reload(self) -> None:
        self.profiles.clear()
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return
        for item in data.get("profiles", []):
            try:
                p = Profile.from_dict(item)
                self.profiles[p.name] = p
            except (KeyError, ValueError, TypeError):
                continue

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {"profiles": [p.to_dict() for p in self.profiles.values()]}
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    def names_for(self, vid: int, pid: int) -> list[str]:
        return sorted(
            name for name, p in self.profiles.items()
            if p.vid == vid and p.pid == pid
        )

    def get(self, name: str) -> Profile | None:
        return self.profiles.get(name)

    def put(self, profile: Profile) -> None:
        self.profiles[profile.name] = profile
        self._save()

    def delete(self, name: str) -> bool:
        if name not in self.profiles:
            return False
        del self.profiles[name]
        self._save()
        return True
