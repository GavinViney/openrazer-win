"""tkinter GUI for openrazer-win.

Shows connected Razer mouse stats + capabilities, exposes DPI /
polling controls, and hosts the profile picker + save-as / apply /
delete flow.

Intentionally minimal — one window, no notebook tabs, no theming
dependency. Matches the tkinter pattern used by the other tools in
this workspace (Tapo C200, PnP Scope, Live Vision).
"""

from __future__ import annotations

import threading
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk

from .mouse import DPIStage, RazerMouse
from .profiles import Profile, ProfileStore
from .transport import DiscoveredDevice, RazerTransport, discover


PADDING = 8


class OpenRazerGUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("openrazer-win")
        self.geometry("520x600")
        self.minsize(480, 560)

        self.devices: list[DiscoveredDevice] = []
        self.current_device: DiscoveredDevice | None = None
        self.store = ProfileStore.open()

        self._build()
        self.after(50, self._refresh_devices)

    # -- layout ----------------------------------------------------------

    def _build(self) -> None:
        root = ttk.Frame(self, padding=PADDING)
        root.pack(fill="both", expand=True)

        # Device row
        dev_row = ttk.Frame(root)
        dev_row.pack(fill="x", pady=(0, PADDING))
        ttk.Label(dev_row, text="Device:").pack(side="left")
        self.device_var = tk.StringVar()
        self.device_combo = ttk.Combobox(
            dev_row, textvariable=self.device_var, state="readonly", width=32
        )
        self.device_combo.pack(side="left", padx=(6, 6))
        self.device_combo.bind("<<ComboboxSelected>>", lambda e: self._on_device_change())
        ttk.Button(dev_row, text="Refresh", command=self._refresh_devices).pack(side="left")

        # Info block
        info = ttk.LabelFrame(root, text="Device info", padding=PADDING)
        info.pack(fill="x", pady=(0, PADDING))
        self.info_vars = {
            k: tk.StringVar(value="–") for k in
            ("Firmware", "Serial", "Max DPI", "Stages (max)", "Kind")
        }
        for i, (label, var) in enumerate(self.info_vars.items()):
            ttk.Label(info, text=f"{label}:").grid(row=i, column=0, sticky="w", padx=(0, 8))
            ttk.Label(info, textvariable=var).grid(row=i, column=1, sticky="w")

        # Current DPI
        dpi = ttk.LabelFrame(root, text="Current DPI", padding=PADDING)
        dpi.pack(fill="x", pady=(0, PADDING))
        ttk.Label(dpi, text="X:").grid(row=0, column=0, sticky="w")
        self.dpi_x_var = tk.StringVar()
        ttk.Entry(dpi, textvariable=self.dpi_x_var, width=8).grid(row=0, column=1, padx=(4, 12))
        ttk.Label(dpi, text="Y:").grid(row=0, column=2, sticky="w")
        self.dpi_y_var = tk.StringVar()
        ttk.Entry(dpi, textvariable=self.dpi_y_var, width=8).grid(row=0, column=3, padx=(4, 12))
        ttk.Button(dpi, text="Apply DPI", command=self._apply_dpi).grid(row=0, column=4)

        # Stages
        stages_frame = ttk.LabelFrame(root, text="Stored DPI stages", padding=PADDING)
        stages_frame.pack(fill="both", expand=True, pady=(0, PADDING))
        cols = ("active", "stage", "x", "y")
        self.stages_tree = ttk.Treeview(
            stages_frame, columns=cols, show="headings", height=6
        )
        for c, w in zip(cols, (60, 60, 100, 100)):
            self.stages_tree.heading(c, text=c.upper())
            self.stages_tree.column(c, width=w, anchor="center")
        self.stages_tree.pack(fill="both", expand=True)

        # Polling
        poll = ttk.LabelFrame(root, text="Polling rate", padding=PADDING)
        poll.pack(fill="x", pady=(0, PADDING))
        self.poll_var = tk.IntVar(value=1000)
        for hz in (125, 500, 1000):
            ttk.Radiobutton(
                poll, text=f"{hz} Hz", variable=self.poll_var, value=hz,
            ).pack(side="left", padx=(0, 12))
        ttk.Button(poll, text="Apply polling", command=self._apply_polling).pack(side="left")

        # Profiles
        prof = ttk.LabelFrame(root, text="Profiles", padding=PADDING)
        prof.pack(fill="x", pady=(0, 0))
        self.profile_var = tk.StringVar()
        self.profile_combo = ttk.Combobox(
            prof, textvariable=self.profile_var, state="readonly", width=28
        )
        self.profile_combo.grid(row=0, column=0, padx=(0, 8))
        ttk.Button(prof, text="Apply", command=self._apply_profile).grid(row=0, column=1)
        ttk.Button(prof, text="Save current as…", command=self._save_profile).grid(row=0, column=2, padx=(8, 0))
        ttk.Button(prof, text="Delete", command=self._delete_profile).grid(row=0, column=3, padx=(8, 0))

        # Status bar
        self.status_var = tk.StringVar(value="Ready.")
        ttk.Label(self, textvariable=self.status_var, relief="sunken", anchor="w").pack(
            fill="x", side="bottom"
        )

    # -- refresh + selection ---------------------------------------------

    def _refresh_devices(self) -> None:
        self._status("Scanning for Razer devices…")
        def work():
            try:
                found = discover()
            except Exception as e:
                self.after(0, lambda: self._status(f"Discovery failed: {e}"))
                return
            self.after(0, lambda: self._devices_ready(found))
        threading.Thread(target=work, daemon=True).start()

    def _devices_ready(self, found: list[DiscoveredDevice]) -> None:
        self.devices = found
        if not found:
            self.device_combo["values"] = []
            self.device_var.set("")
            self.current_device = None
            self._clear_info()
            self._status("No known Razer devices found.")
            return
        labels = [f"{d.spec.name}  (0x{d.spec.pid:04x})" for d in found]
        self.device_combo["values"] = labels
        self.device_combo.current(0)
        self._on_device_change()

    def _on_device_change(self) -> None:
        idx = self.device_combo.current()
        if idx < 0 or idx >= len(self.devices):
            return
        self.current_device = self.devices[idx]
        self._reload_from_device()
        self._reload_profile_list()

    # -- device read -----------------------------------------------------

    def _reload_from_device(self) -> None:
        dev = self.current_device
        if dev is None:
            return
        self._status(f"Reading {dev.spec.name}…")

        def work():
            try:
                with RazerTransport(dev) as t:
                    m = RazerMouse(t)
                    firmware = m.get_firmware_version()
                    serial = m.get_serial()
                    dpi_x, dpi_y = m.get_current_dpi()
                    active, stages = m.get_dpi_stages()
                    poll = m.get_polling_rate()
            except Exception as e:
                self.after(0, lambda: self._status(f"Read failed: {e}"))
                return
            self.after(0, lambda: self._render_device(
                firmware, serial, dpi_x, dpi_y, active, stages, poll,
            ))

        threading.Thread(target=work, daemon=True).start()

    def _render_device(
        self, firmware: str, serial: str,
        dpi_x: int, dpi_y: int, active: int, stages: list[DPIStage], poll: int,
    ) -> None:
        dev = self.current_device
        if dev is None:
            return
        self.info_vars["Firmware"].set(firmware)
        # Trim serial to last 6 chars for display privacy; full serial via CLI info.
        shown_serial = f"…{serial[-6:]}" if len(serial) > 6 else serial
        self.info_vars["Serial"].set(shown_serial)
        self.info_vars["Max DPI"].set(str(dev.spec.max_dpi))
        self.info_vars["Stages (max)"].set(str(dev.spec.dpi_stages))
        self.info_vars["Kind"].set(dev.spec.kind.value)

        self.dpi_x_var.set(str(dpi_x))
        self.dpi_y_var.set(str(dpi_y))

        for item in self.stages_tree.get_children():
            self.stages_tree.delete(item)
        for s in stages:
            marker = "★" if s.stage == active else ""
            self.stages_tree.insert(
                "", "end", values=(marker, s.stage, s.dpi_x, s.dpi_y),
            )

        if poll:
            self.poll_var.set(poll)

        self._status(f"{dev.spec.name}: read OK.")

    def _clear_info(self) -> None:
        for var in self.info_vars.values():
            var.set("–")
        self.dpi_x_var.set("")
        self.dpi_y_var.set("")
        for item in self.stages_tree.get_children():
            self.stages_tree.delete(item)

    # -- device write ----------------------------------------------------

    def _apply_dpi(self) -> None:
        dev = self.current_device
        if dev is None:
            return
        try:
            x = int(self.dpi_x_var.get())
            y = int(self.dpi_y_var.get())
        except ValueError:
            messagebox.showerror("Bad input", "DPI values must be integers.")
            return
        self._status(f"Setting DPI {x} x {y}…")

        def work():
            try:
                with RazerTransport(dev) as t:
                    RazerMouse(t).set_current_dpi(x, y)
            except Exception as e:
                self.after(0, lambda: self._status(f"Set DPI failed: {e}"))
                return
            self.after(0, lambda: self._status(f"DPI set to {x} x {y}."))
            self.after(0, self._reload_from_device)

        threading.Thread(target=work, daemon=True).start()

    def _apply_polling(self) -> None:
        dev = self.current_device
        if dev is None:
            return
        hz = self.poll_var.get()
        self._status(f"Setting polling {hz} Hz…")

        def work():
            try:
                with RazerTransport(dev) as t:
                    RazerMouse(t).set_polling_rate(hz)
            except Exception as e:
                self.after(0, lambda: self._status(f"Set polling failed: {e}"))
                return
            self.after(0, lambda: self._status(f"Polling set to {hz} Hz."))
            self.after(0, self._reload_from_device)

        threading.Thread(target=work, daemon=True).start()

    # -- profiles --------------------------------------------------------

    def _reload_profile_list(self) -> None:
        dev = self.current_device
        if dev is None:
            self.profile_combo["values"] = []
            self.profile_var.set("")
            return
        names = self.store.names_for(dev.spec.vid, dev.spec.pid)
        self.profile_combo["values"] = names
        if names:
            self.profile_combo.current(0)
        else:
            self.profile_var.set("")

    def _save_profile(self) -> None:
        dev = self.current_device
        if dev is None:
            return
        name = simpledialog.askstring(
            "Save profile as", "Profile name:", parent=self,
        )
        if not name:
            return
        self._status(f"Capturing '{name}'…")

        def work():
            try:
                with RazerTransport(dev) as t:
                    profile = Profile.capture(name, RazerMouse(t))
                self.store.put(profile)
            except Exception as e:
                self.after(0, lambda: self._status(f"Save failed: {e}"))
                return
            self.after(0, lambda: self._status(f"Saved profile '{name}'."))
            self.after(0, self._reload_profile_list)

        threading.Thread(target=work, daemon=True).start()

    def _apply_profile(self) -> None:
        dev = self.current_device
        if dev is None:
            return
        name = self.profile_var.get()
        if not name:
            return
        profile = self.store.get(name)
        if profile is None:
            return
        if not messagebox.askyesno(
            "Apply profile",
            f"Apply '{name}' to {dev.spec.name}?\n\n"
            "This will overwrite the mouse's stored DPI stages and polling rate.",
            parent=self,
        ):
            return
        self._status(f"Applying '{name}'…")

        def work():
            try:
                with RazerTransport(dev) as t:
                    profile.apply(RazerMouse(t))
            except Exception as e:
                self.after(0, lambda: self._status(f"Apply failed: {e}"))
                return
            self.after(0, lambda: self._status(f"Applied profile '{name}'."))
            self.after(0, self._reload_from_device)

        threading.Thread(target=work, daemon=True).start()

    def _delete_profile(self) -> None:
        name = self.profile_var.get()
        if not name:
            return
        if not messagebox.askyesno(
            "Delete profile", f"Delete '{name}' from the profile store?",
            parent=self,
        ):
            return
        if self.store.delete(name):
            self._status(f"Deleted profile '{name}'.")
            self._reload_profile_list()

    # -- misc ------------------------------------------------------------

    def _status(self, msg: str) -> None:
        self.status_var.set(msg)


def main() -> int:
    app = OpenRazerGUI()
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
