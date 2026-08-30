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

import datetime as _dt

from .mouse import (
    BTN_ACTION_DEFAULT, BTN_ACTION_DISABLE, BTN_ACTION_KEYBOARD,
    ButtonAction, DPIStage, LED_LOGO, LED_SCROLL_WHEEL, RazerMouse,
)
from .profiles import Profile, ProfileStore
from .transport import DiscoveredDevice, RazerTransport, discover


PADDING = 8


class OpenRazerGUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("openrazer-win")
        self.geometry("560x780")
        self.minsize(520, 720)

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

        # Lighting
        lighting = ttk.LabelFrame(root, text="Lighting", padding=PADDING)
        lighting.pack(fill="x", pady=(0, PADDING))

        ttk.Label(lighting, text="Wheel:").grid(row=0, column=0, sticky="w")
        self.wheel_bright_var = tk.IntVar(value=178)
        tk.Scale(
            lighting, from_=0, to=255, orient="horizontal",
            variable=self.wheel_bright_var, length=220, showvalue=True,
        ).grid(row=0, column=1, columnspan=3, sticky="ew", padx=(4, 8))

        ttk.Label(lighting, text="Logo:").grid(row=1, column=0, sticky="w")
        self.logo_bright_var = tk.IntVar(value=178)
        tk.Scale(
            lighting, from_=0, to=255, orient="horizontal",
            variable=self.logo_bright_var, length=220, showvalue=True,
        ).grid(row=1, column=1, columnspan=3, sticky="ew", padx=(4, 8))

        ttk.Button(lighting, text="Apply brightness", command=self._apply_brightness).grid(
            row=2, column=0, columnspan=2, sticky="w", pady=(4, 8),
        )

        ttk.Label(lighting, text="Effect:").grid(row=3, column=0, sticky="w")
        self.effect_var = tk.StringVar(value="static")
        ttk.Combobox(
            lighting, textvariable=self.effect_var,
            values=["none", "static", "spectrum", "wave"], state="readonly", width=10,
        ).grid(row=3, column=1, sticky="w", padx=(4, 12))

        ttk.Label(lighting, text="Colour:").grid(row=3, column=2, sticky="w")
        self.color_hex_var = tk.StringVar(value="#00ffff")
        self.color_btn = tk.Button(
            lighting, text="  Pick  ", bg=self.color_hex_var.get(),
            command=self._pick_color, width=8, relief="raised",
        )
        self.color_btn.grid(row=3, column=3, sticky="w", padx=(4, 0))

        ttk.Button(lighting, text="Apply effect", command=self._apply_effect).grid(
            row=4, column=0, columnspan=2, sticky="w", pady=(4, 0),
        )

        # Buttons launch
        btn_row = ttk.Frame(root)
        btn_row.pack(fill="x", pady=(0, PADDING))
        ttk.Button(btn_row, text="Test + remap buttons…", command=self._open_button_tester).pack(side="left")
        ttk.Label(btn_row, text="   (opens a window to see button events and write remaps)").pack(side="left")

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
                    brightness = m.get_all_brightness()
            except Exception as e:
                self.after(0, lambda: self._status(f"Read failed: {e}"))
                return
            self.after(0, lambda: self._render_device(
                firmware, serial, dpi_x, dpi_y, active, stages, poll, brightness,
            ))

        threading.Thread(target=work, daemon=True).start()

    def _render_device(
        self, firmware: str, serial: str,
        dpi_x: int, dpi_y: int, active: int, stages: list[DPIStage], poll: int,
        brightness: dict[int, int] | None = None,
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

        if brightness:
            if LED_SCROLL_WHEEL in brightness:
                self.wheel_bright_var.set(brightness[LED_SCROLL_WHEEL])
            if LED_LOGO in brightness:
                self.logo_bright_var.set(brightness[LED_LOGO])

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

    # -- lighting --------------------------------------------------------

    def _pick_color(self) -> None:
        from tkinter import colorchooser
        rgb, hex_col = colorchooser.askcolor(
            color=self.color_hex_var.get(), parent=self, title="Pick colour",
        )
        if hex_col:
            self.color_hex_var.set(hex_col)
            self.color_btn.config(bg=hex_col)

    def _apply_brightness(self) -> None:
        dev = self.current_device
        if dev is None:
            return
        wheel = self.wheel_bright_var.get()
        logo = self.logo_bright_var.get()
        self._status(f"Setting brightness wheel={wheel} logo={logo}…")

        def work():
            try:
                with RazerTransport(dev) as t:
                    m = RazerMouse(t)
                    m.set_brightness(wheel, led=LED_SCROLL_WHEEL)
                    m.set_brightness(logo, led=LED_LOGO)
            except Exception as e:
                self.after(0, lambda: self._status(f"Brightness set failed: {e}"))
                return
            self.after(0, lambda: self._status(
                f"Brightness applied: wheel={wheel}, logo={logo}."
            ))

        threading.Thread(target=work, daemon=True).start()

    def _apply_effect(self) -> None:
        dev = self.current_device
        if dev is None:
            return
        effect = self.effect_var.get()
        hex_col = self.color_hex_var.get()
        try:
            r = int(hex_col[1:3], 16)
            g = int(hex_col[3:5], 16)
            b = int(hex_col[5:7], 16)
        except (ValueError, IndexError):
            r, g, b = 0, 255, 255
        self._status(f"Setting effect '{effect}'…")

        def work():
            try:
                with RazerTransport(dev) as t:
                    m = RazerMouse(t)
                    if effect == "none":
                        m.set_effect_none()
                    elif effect == "static":
                        m.set_effect_static(r, g, b)
                    elif effect == "spectrum":
                        m.set_effect_spectrum()
                    elif effect == "wave":
                        m.set_effect_wave(direction=1)
            except Exception as e:
                self.after(0, lambda: self._status(f"Effect set failed: {e}"))
                return
            self.after(0, lambda: self._status(f"Effect '{effect}' applied."))

        threading.Thread(target=work, daemon=True).start()

    # -- button tester ---------------------------------------------------

    def _open_button_tester(self) -> None:
        if self.current_device is None:
            messagebox.showinfo("No device", "Select a device first.")
            return
        ButtonTestWindow(self, self.current_device)

    # -- misc ------------------------------------------------------------

    def _status(self, msg: str) -> None:
        self.status_var.set(msg)


class ButtonTestWindow(tk.Toplevel):
    """Test + remap tool. Live event log for physical-button-ID mapping,
    current bindings table, and a write form for remaps.

    First-time write pattern: read current, write same value back as a no-op
    verification, then write the real change once the round-trip is confirmed.
    """

    BTN_IDS_TO_SCAN = list(range(1, 12))

    def __init__(self, parent: OpenRazerGUI, device: DiscoveredDevice):
        super().__init__(parent)
        self.parent_gui = parent
        self.device = device
        self.title(f"Buttons — {device.spec.name}")
        self.geometry("640x680")
        self.transient(parent)

        self._build()
        self.after(50, self._reload_bindings)

    # ---- layout ----

    def _build(self) -> None:
        root = ttk.Frame(self, padding=PADDING)
        root.pack(fill="both", expand=True)

        # Live event log
        log_frame = ttk.LabelFrame(
            root, text="Live event log — click inside, then press keys or mouse buttons",
            padding=PADDING,
        )
        log_frame.pack(fill="both", expand=True, pady=(0, PADDING))

        self.log_text = tk.Text(log_frame, height=10, wrap="none", font=("Consolas", 9))
        self.log_text.pack(fill="both", expand=True)
        self.log_text.insert("end", "(click here, then press keys / mouse buttons to see what Windows reports)\n")
        self.log_text.bind("<KeyPress>", self._on_key)
        self.log_text.bind("<Button>", self._on_mouse)
        self.log_text.bind("<MouseWheel>", self._on_wheel)

        log_row = ttk.Frame(root)
        log_row.pack(fill="x", pady=(0, PADDING))
        ttk.Button(log_row, text="Clear log", command=self._clear_log).pack(side="left")
        self.capture_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            log_row, text="Auto-fill 'Payload' from next key press",
            variable=self.capture_var,
        ).pack(side="left", padx=(12, 0))

        # Current bindings table
        bindings_frame = ttk.LabelFrame(root, text="Current bindings (profile 0)", padding=PADDING)
        bindings_frame.pack(fill="both", expand=True, pady=(0, PADDING))
        cols = ("id", "type", "summary", "raw")
        self.tree = ttk.Treeview(bindings_frame, columns=cols, show="headings", height=8)
        for c, w in zip(cols, (50, 80, 200, 200)):
            self.tree.heading(c, text=c.upper())
            self.tree.column(c, width=w, anchor="w")
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", self._on_row_select)

        ttk.Button(bindings_frame, text="Reload bindings", command=self._reload_bindings).pack(anchor="w", pady=(6, 0))

        # Remap form
        remap = ttk.LabelFrame(root, text="Remap", padding=PADDING)
        remap.pack(fill="x")

        ttk.Label(remap, text="Button ID:").grid(row=0, column=0, sticky="w")
        self.btn_var = tk.IntVar(value=1)
        self.btn_combo = ttk.Combobox(
            remap, textvariable=self.btn_var, width=5, state="readonly",
            values=self.BTN_IDS_TO_SCAN,
        )
        self.btn_combo.grid(row=0, column=1, padx=(4, 12), sticky="w")

        ttk.Label(remap, text="Action:").grid(row=0, column=2, sticky="w")
        self.action_var = tk.StringVar(value="default")
        self.action_combo = ttk.Combobox(
            remap, textvariable=self.action_var, width=12, state="readonly",
            values=("default", "keyboard", "disable"),
        )
        self.action_combo.grid(row=0, column=3, padx=(4, 12), sticky="w")

        ttk.Label(remap, text="Payload (hex):").grid(row=1, column=0, sticky="w", pady=(6, 0))
        self.payload_var = tk.StringVar()
        ttk.Entry(remap, textvariable=self.payload_var, width=10).grid(
            row=1, column=1, padx=(4, 12), sticky="w", pady=(6, 0),
        )
        ttk.Label(
            remap, text="e.g. 09 for HID key 'F', 01 for mouse button 1"
        ).grid(row=1, column=2, columnspan=2, sticky="w", pady=(6, 0))

        btn_row = ttk.Frame(remap)
        btn_row.grid(row=2, column=0, columnspan=4, sticky="w", pady=(10, 0))
        ttk.Button(btn_row, text="Read only (no write)", command=self._read_selected).pack(side="left")
        ttk.Button(btn_row, text="Write same value (no-op test)", command=self._write_noop).pack(side="left", padx=(6, 0))
        ttk.Button(btn_row, text="Write from form (LIVE)", command=self._write_from_form).pack(side="left", padx=(6, 0))

        # Status
        self.status_var = tk.StringVar(value="Ready. Click the log to capture events.")
        ttk.Label(self, textvariable=self.status_var, relief="sunken", anchor="w").pack(fill="x", side="bottom")

    # ---- event logging ----

    def _log(self, kind: str, detail: str) -> None:
        ts = _dt.datetime.now().strftime("%H:%M:%S.%f")[:-3]
        self.log_text.insert("end", f"{ts}  {kind:6s}  {detail}\n")
        self.log_text.see("end")

    def _on_key(self, event) -> str:
        self._log("KEY", f"keysym={event.keysym!r:12s}  keycode={event.keycode}  char={event.char!r}")
        if self.capture_var.get():
            self.payload_var.set(f"{event.keycode & 0xFF:02x}")
            self.action_var.set("keyboard")
            self.capture_var.set(False)
            self._status(f"Captured keycode 0x{event.keycode & 0xFF:02x} into payload.")
        return "break"

    def _on_mouse(self, event) -> None:
        self._log("MOUSE", f"button={event.num}  x={event.x} y={event.y}")

    def _on_wheel(self, event) -> None:
        self._log("WHEEL", f"delta={event.delta}")

    def _clear_log(self) -> None:
        self.log_text.delete("1.0", "end")

    # ---- bindings table ----

    def _reload_bindings(self) -> None:
        self._status("Reading bindings…")
        for r in self.tree.get_children():
            self.tree.delete(r)

        def work():
            rows: list[ButtonAction | tuple[int, str]] = []
            with RazerTransport(self.device) as t:
                m = RazerMouse(t)
                for bid in self.BTN_IDS_TO_SCAN:
                    try:
                        rows.append(m.get_button_action(button_id=bid, profile=0))
                    except Exception as e:
                        rows.append((bid, f"failed: {e}"))
            self.after(0, lambda: self._render_bindings(rows))

        threading.Thread(target=work, daemon=True).start()

    def _render_bindings(self, rows) -> None:
        for r in rows:
            if isinstance(r, ButtonAction):
                type_name = {
                    BTN_ACTION_DEFAULT: "default", BTN_ACTION_KEYBOARD: "keyboard",
                    BTN_ACTION_DISABLE: "disabled",
                }.get(r.action_type, f"0x{r.action_type:02x}")
                self.tree.insert("", "end", values=(r.button_id, type_name, r.summary, r.payload.hex()))
            else:
                bid, msg = r
                self.tree.insert("", "end", values=(bid, "-", msg, ""))
        self._status("Bindings read.")

    def _on_row_select(self, event) -> None:
        sel = self.tree.selection()
        if not sel:
            return
        vals = self.tree.item(sel[0], "values")
        try:
            self.btn_var.set(int(vals[0]))
        except (ValueError, IndexError):
            pass

    # ---- read / write ----

    def _read_selected(self) -> None:
        bid = self.btn_var.get()
        self._status(f"Reading button {bid}…")

        def work():
            try:
                with RazerTransport(self.device) as t:
                    a = RazerMouse(t).get_button_action(button_id=bid, profile=0)
            except Exception as e:
                self.after(0, lambda: self._status(f"Read failed: {e}"))
                return
            self.after(0, lambda: self._show_read(a))

        threading.Thread(target=work, daemon=True).start()

    def _show_read(self, a: ButtonAction) -> None:
        type_name = {
            BTN_ACTION_DEFAULT: "default", BTN_ACTION_KEYBOARD: "keyboard",
            BTN_ACTION_DISABLE: "disabled",
        }.get(a.action_type, f"0x{a.action_type:02x}")
        self.action_var.set(type_name if type_name in ("default", "keyboard", "disable") else "keyboard")
        if a.action_type == BTN_ACTION_DEFAULT:
            self.payload_var.set(f"{a.payload[0]:02x}")
        elif a.action_type == BTN_ACTION_KEYBOARD:
            self.payload_var.set(f"{a.payload[1]:02x}")
        else:
            self.payload_var.set(a.payload[:2].hex())
        self._status(f"Button {a.button_id}: {a.summary}  (form populated)")

    def _write_noop(self) -> None:
        """Read current binding, immediately write it back unchanged, re-read.
        Safest possible write test — confirms the write path works with zero
        risk of altering behaviour."""
        bid = self.btn_var.get()
        self._status(f"No-op write test on button {bid}…")

        def work():
            try:
                with RazerTransport(self.device) as t:
                    m = RazerMouse(t)
                    before = m.get_button_action(button_id=bid, profile=0)
                    m.set_button_action(
                        button_id=bid,
                        action_type=before.action_type,
                        payload=before.payload,
                        sub_type=before.sub_type,
                        profile=0,
                    )
                    after = m.get_button_action(button_id=bid, profile=0)
            except Exception as e:
                self.after(0, lambda: self._status(f"No-op write failed: {e}"))
                return
            if (after.action_type == before.action_type and
                    after.payload == before.payload):
                self.after(0, lambda: self._status(
                    f"No-op write OK: btn {bid} unchanged after round-trip "
                    f"({before.summary})."
                ))
            else:
                self.after(0, lambda: self._status(
                    f"WRITE PATH MISMATCH on btn {bid}: before={before.summary} "
                    f"after={after.summary} — protocol layout wrong for SET."
                ))
            self.after(0, self._reload_bindings)

        threading.Thread(target=work, daemon=True).start()

    def _write_from_form(self) -> None:
        bid = self.btn_var.get()
        action = self.action_var.get()
        raw = self.payload_var.get().strip().replace("0x", "").replace(" ", "")
        try:
            code = int(raw, 16) & 0xFF
        except ValueError:
            messagebox.showerror("Bad payload", "Payload must be a hex byte (e.g. '09').")
            return

        if action == "default":
            action_type = BTN_ACTION_DEFAULT
            sub_type = 0x01
            payload = bytes([code, 0x00, 0x00, 0x00])
        elif action == "keyboard":
            action_type = BTN_ACTION_KEYBOARD
            sub_type = 0x02
            payload = bytes([0x00, code, 0x00, 0x00])
        else:  # disable
            action_type = BTN_ACTION_DISABLE
            sub_type = 0x00
            payload = bytes([0x00, 0x00, 0x00, 0x00])

        if not messagebox.askyesno(
            "Write button binding",
            f"Write btn {bid} = {action} 0x{code:02x} to the mouse?\n\n"
            "This is a live write. If the format is wrong the button may "
            "stop responding until reset.",
            parent=self,
        ):
            return

        self._status(f"Writing btn {bid}…")

        def work():
            try:
                with RazerTransport(self.device) as t:
                    m = RazerMouse(t)
                    m.set_button_action(
                        button_id=bid, action_type=action_type,
                        payload=payload, sub_type=sub_type, profile=0,
                    )
                    after = m.get_button_action(button_id=bid, profile=0)
            except Exception as e:
                self.after(0, lambda: self._status(f"Write failed: {e}"))
                return
            self.after(0, lambda: self._status(
                f"Wrote btn {bid}. Read-back: {after.summary}"
            ))
            self.after(0, self._reload_bindings)

        threading.Thread(target=work, daemon=True).start()

    def _status(self, msg: str) -> None:
        self.status_var.set(msg)


def main() -> int:
    app = OpenRazerGUI()
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
