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

from . import button_labels
from .hid_keys import HID_NAMES, hid_name, vk_to_hid
from .mouse import (
    BTN_ACTION_DEFAULT, BTN_ACTION_DISABLE, BTN_ACTION_KEYBOARD,
    ButtonAction, DPIStage, LED_LOGO, LED_SCROLL_WHEEL, RazerMouse,
)
from .profiles import Profile, ProfileStore
from .transport import DiscoveredDevice, RazerTransport, discover


PADDING = 8


def _hex_to_rgb(hex_col: str) -> tuple[int, int, int]:
    h = hex_col.lstrip("#")
    if len(h) != 6:
        return (0, 0, 0)
    try:
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
    except ValueError:
        return (0, 0, 0)


class OpenRazerGUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("openrazer-win")
        self.geometry("1120x660")
        self.minsize(960, 600)

        self._apply_dark_theme()

        self.devices: list[DiscoveredDevice] = []
        self.current_device: DiscoveredDevice | None = None
        self.store = ProfileStore.open()

        self._build()
        self.after(50, self._refresh_devices)

    def _apply_dark_theme(self) -> None:
        """Dark palette applied globally via ttk.Style + tk_setPalette. Covers both
        the main window and the ButtonTestWindow (ttk styles + tk defaults are
        process-wide). Colour swatches keep their explicit bg= and stay vivid."""
        BG = "#1e1e1e"      # window background
        FG = "#e0e0e0"      # primary text
        FIELD = "#2b2b2b"   # entry / combobox / treeview / text backgrounds
        ACTIVE = "#3c3c3c"  # borders, hover, headings
        SELECT = "#00ffff"  # selection accent (cyberpunk cyan — matches nx-deck)

        style = ttk.Style(self)
        try:
            style.theme_use("clam")  # 'clam' allows full colour control; vista/xpnative don't
        except tk.TclError:
            pass

        style.configure(".", background=BG, foreground=FG, fieldbackground=FIELD,
                        bordercolor=ACTIVE, lightcolor=ACTIVE, darkcolor=ACTIVE,
                        troughcolor=FIELD, insertcolor=FG, selectbackground=SELECT,
                        selectforeground=BG)
        style.configure("TFrame", background=BG)
        style.configure("TLabel", background=BG, foreground=FG)
        style.configure("TLabelframe", background=BG, foreground=FG, bordercolor=ACTIVE)
        style.configure("TLabelframe.Label", background=BG, foreground=FG)
        style.configure("TButton", background=FIELD, foreground=FG, bordercolor=ACTIVE, focuscolor=ACTIVE)
        style.map("TButton",
                  background=[("active", ACTIVE), ("pressed", ACTIVE)],
                  foreground=[("disabled", "#777777")])
        style.configure("TEntry", fieldbackground=FIELD, foreground=FG, insertcolor=FG, bordercolor=ACTIVE)
        style.configure("TCombobox", fieldbackground=FIELD, foreground=FG,
                        background=FIELD, arrowcolor=FG, bordercolor=ACTIVE)
        style.map("TCombobox",
                  fieldbackground=[("readonly", FIELD)],
                  foreground=[("readonly", FG)],
                  selectbackground=[("readonly", FIELD)])
        style.configure("TRadiobutton", background=BG, foreground=FG, indicatorcolor=FIELD)
        style.map("TRadiobutton", background=[("active", BG)], indicatorcolor=[("selected", SELECT)])
        style.configure("TCheckbutton", background=BG, foreground=FG, indicatorcolor=FIELD)
        style.map("TCheckbutton", background=[("active", BG)], indicatorcolor=[("selected", SELECT)])
        style.configure("Treeview", background=FIELD, foreground=FG, fieldbackground=FIELD, bordercolor=ACTIVE)
        style.configure("Treeview.Heading", background=ACTIVE, foreground=FG, bordercolor=BG)
        style.map("Treeview", background=[("selected", SELECT)], foreground=[("selected", BG)])
        style.configure("TScrollbar", background=FIELD, troughcolor=BG, arrowcolor=FG, bordercolor=ACTIVE)

        # tk (non-ttk) widget defaults — tk.Scale, tk.Text, tk.Button (swatches keep explicit bg=)
        self.tk_setPalette(
            background=BG, foreground=FG,
            activeBackground=ACTIVE, activeForeground=FG,
            selectBackground=SELECT, selectForeground=BG,
            insertBackground=FG, troughColor=FIELD,
            highlightBackground=ACTIVE, highlightColor=SELECT,
        )

        # Store for widgets that need explicit colours (log_text etc.)
        self._dark = {"bg": BG, "fg": FG, "field": FIELD, "active": ACTIVE, "select": SELECT}

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

        # Two-column body: left = device/DPI/polling/buttons, right = lighting
        cols = ttk.Frame(root)
        cols.pack(fill="both", expand=True)
        left = ttk.Frame(cols)
        left.pack(side="left", fill="both", expand=True, padx=(0, PADDING))
        right = ttk.Frame(cols)
        right.pack(side="left", fill="both", expand=True)

        # Info block
        info = ttk.LabelFrame(left, text="Device info", padding=PADDING)
        info.pack(fill="x", pady=(0, PADDING))
        self.info_vars = {
            k: tk.StringVar(value="–") for k in
            ("Firmware", "Serial", "Max DPI", "Stages (max)", "Kind")
        }
        for i, (label, var) in enumerate(self.info_vars.items()):
            ttk.Label(info, text=f"{label}:").grid(row=i, column=0, sticky="w", padx=(0, 8))
            ttk.Label(info, textvariable=var).grid(row=i, column=1, sticky="w")

        # Current DPI
        dpi = ttk.LabelFrame(left, text="Current DPI", padding=PADDING)
        dpi.pack(fill="x", pady=(0, PADDING))
        ttk.Label(dpi, text="X:").grid(row=0, column=0, sticky="w")
        self.dpi_x_var = tk.StringVar()
        ttk.Entry(dpi, textvariable=self.dpi_x_var, width=8).grid(row=0, column=1, padx=(4, 12))
        ttk.Label(dpi, text="Y:").grid(row=0, column=2, sticky="w")
        self.dpi_y_var = tk.StringVar()
        ttk.Entry(dpi, textvariable=self.dpi_y_var, width=8).grid(row=0, column=3, padx=(4, 12))
        ttk.Button(dpi, text="Apply DPI", command=self._apply_dpi).grid(row=0, column=4)

        # Stages
        stages_frame = ttk.LabelFrame(left, text="Stored DPI stages", padding=PADDING)
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
        poll = ttk.LabelFrame(left, text="Polling rate", padding=PADDING)
        poll.pack(fill="x", pady=(0, PADDING))
        self.poll_var = tk.IntVar(value=1000)
        for hz in (125, 500, 1000):
            ttk.Radiobutton(
                poll, text=f"{hz} Hz", variable=self.poll_var, value=hz,
            ).pack(side="left", padx=(0, 12))
        ttk.Button(poll, text="Apply polling", command=self._apply_polling).pack(side="left")

        # Lighting
        lighting = ttk.LabelFrame(right, text="Lighting", padding=PADDING)
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

        self.include_underglow_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            lighting, text="Include underglow (uniform colour for effect above)",
            variable=self.include_underglow_var,
        ).grid(row=4, column=0, columnspan=4, sticky="w", pady=(4, 0))

        ttk.Button(lighting, text="Apply effect", command=self._apply_effect).grid(
            row=5, column=0, columnspan=2, sticky="w", pady=(4, 0),
        )

        # Per-LED colour grid
        per_led = ttk.LabelFrame(right, text="Per-LED colours (overrides effect above)", padding=PADDING)
        per_led.pack(fill="x", pady=(0, PADDING))

        # Wheel + logo row
        wl_row = ttk.Frame(per_led)
        wl_row.pack(fill="x", pady=(0, 6))
        ttk.Label(wl_row, text="Wheel:").pack(side="left")
        self.wheel_led_color = "#00ffff"
        self.wheel_led_btn = tk.Button(
            wl_row, text="  ", bg=self.wheel_led_color, width=3, relief="raised",
            command=lambda: self._pick_led_color("wheel"),
        )
        self.wheel_led_btn.pack(side="left", padx=(4, 16))

        ttk.Label(wl_row, text="Logo:").pack(side="left")
        self.logo_led_color = "#00ffff"
        self.logo_led_btn = tk.Button(
            wl_row, text="  ", bg=self.logo_led_color, width=3, relief="raised",
            command=lambda: self._pick_led_color("logo"),
        )
        self.logo_led_btn.pack(side="left", padx=(4, 0))

        # Underglow strip: 11 swatches left-to-right
        under_frame = ttk.Frame(per_led)
        under_frame.pack(fill="x", pady=(0, 6))
        ttk.Label(under_frame, text="Underglow (L → R):").pack(side="left", padx=(0, 6))
        self.underglow_colors: list[str] = ["#00ffff"] * 11
        self.underglow_btns: list[tk.Button] = []
        for i in range(11):
            b = tk.Button(
                under_frame, text=str(i + 1), bg=self.underglow_colors[i],
                width=2, relief="raised",
                command=lambda idx=i: self._pick_led_color(f"under_{idx}"),
            )
            b.pack(side="left", padx=1)
            self.underglow_btns.append(b)

        # Actions row
        actions = ttk.Frame(per_led)
        actions.pack(fill="x")
        ttk.Button(actions, text="Sync all → wheel colour", command=self._sync_all_to_wheel).pack(side="left")
        ttk.Button(actions, text="All off", command=self._all_leds_off).pack(side="left", padx=(6, 0))
        ttk.Button(actions, text="Apply per-LED", command=self._apply_per_led).pack(side="left", padx=(16, 0))

        # Buttons launch
        btn_row = ttk.Frame(left)
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

    def _pick_led_color(self, target: str) -> None:
        from tkinter import colorchooser
        current = self._get_led_color(target)
        _, hex_col = colorchooser.askcolor(color=current, parent=self, title="Pick LED colour")
        if not hex_col:
            return
        self._set_led_color(target, hex_col)

    def _get_led_color(self, target: str) -> str:
        if target == "wheel":
            return self.wheel_led_color
        if target == "logo":
            return self.logo_led_color
        if target.startswith("under_"):
            return self.underglow_colors[int(target.split("_")[1])]
        return "#000000"

    def _set_led_color(self, target: str, hex_col: str) -> None:
        if target == "wheel":
            self.wheel_led_color = hex_col
            self.wheel_led_btn.config(bg=hex_col)
        elif target == "logo":
            self.logo_led_color = hex_col
            self.logo_led_btn.config(bg=hex_col)
        elif target.startswith("under_"):
            idx = int(target.split("_")[1])
            self.underglow_colors[idx] = hex_col
            self.underglow_btns[idx].config(bg=hex_col)

    def _sync_all_to_wheel(self) -> None:
        col = self.wheel_led_color
        self._set_led_color("logo", col)
        for i in range(11):
            self._set_led_color(f"under_{i}", col)

    def _all_leds_off(self) -> None:
        for target in ("wheel", "logo"):
            self._set_led_color(target, "#000000")
        for i in range(11):
            self._set_led_color(f"under_{i}", "#000000")

    def _apply_per_led(self) -> None:
        dev = self.current_device
        if dev is None:
            return
        wheel_rgb = _hex_to_rgb(self.wheel_led_color)
        logo_rgb = _hex_to_rgb(self.logo_led_color)
        under_rgb = [_hex_to_rgb(c) for c in self.underglow_colors]
        self._status("Writing per-LED colours…")

        def work():
            try:
                with RazerTransport(dev) as t:
                    m = RazerMouse(t)
                    # Wheel and logo — try per-zone static writes first
                    m.set_effect_static(*wheel_rgb, led=LED_SCROLL_WHEEL)
                    m.set_effect_static(*logo_rgb, led=LED_LOGO)
                    # Underglow — custom frame with 11 individual triplets
                    rgb_bytes = b"".join(bytes(c) for c in under_rgb)
                    m.set_custom_frame(row=0, start_col=0, stop_col=10, rgb_data=rgb_bytes)
                    m.set_effect_custom()
            except Exception as e:
                self.after(0, lambda: self._status(f"Per-LED apply failed: {e}"))
                return
            self.after(0, lambda: self._status("Per-LED colours applied."))

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

        include_underglow = self.include_underglow_var.get()

        def work():
            try:
                with RazerTransport(dev) as t:
                    m = RazerMouse(t)
                    if effect == "none":
                        m.set_effect_none()
                        if include_underglow:
                            m.set_underglow_off()
                    elif effect == "static":
                        m.set_effect_static(r, g, b)
                        if include_underglow:
                            m.set_underglow_static(r, g, b)
                    elif effect == "spectrum":
                        m.set_effect_spectrum()
                        # No spectrum equivalent for underglow custom frame;
                        # leave underglow at whatever it currently shows.
                    elif effect == "wave":
                        m.set_effect_wave(direction=1)
                        # Same — wave has no per-LED analog via custom frame.
            except Exception as e:
                self.after(0, lambda: self._status(f"Effect set failed: {e}"))
                return
            self.after(0, lambda: self._status(
                f"Effect '{effect}' applied" + (
                    " (wheel+logo+underglow)." if include_underglow and effect in ("static", "none")
                    else " (wheel+logo only — spectrum/wave don't apply to underglow strip)."
                    if effect in ("spectrum", "wave")
                    else "."
                )
            ))

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

    # Some Razer mice expose wheel-tilt and other extras at button IDs above 11
    # (Basilisk V3 wheel tilts are commonly in the 12-15 range). Scan wider so
    # any mapped button is visible in the bindings table AND discoverable by
    # the log enrichment. Unmapped IDs return status 0x03 and show as "failed".
    BTN_IDS_TO_SCAN = list(range(1, 21))

    def __init__(self, parent: OpenRazerGUI, device: DiscoveredDevice):
        super().__init__(parent)
        self.parent_gui = parent
        self.device = device
        self.title(f"Buttons — {device.spec.name}")
        self.geometry("640x680")
        self.transient(parent)

        self.labels: dict[int, str] = button_labels.load_for(device)

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

        _d = getattr(self.master, "_dark", {"field": "white", "fg": "black"})
        self.log_text = tk.Text(
            log_frame, height=10, wrap="none", font=("Consolas", 9),
            bg=_d["field"], fg=_d["fg"], insertbackground=_d["fg"],
            selectbackground=_d.get("select", "#3c3c3c"),
        )
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

        bindings_btns = ttk.Frame(bindings_frame)
        bindings_btns.pack(anchor="w", pady=(6, 0))
        ttk.Button(bindings_btns, text="Reload bindings", command=self._reload_bindings).pack(side="left")
        ttk.Button(
            bindings_btns, text="Rebind selected to key…",
            command=self._open_rebind_modal,
        ).pack(side="left", padx=(6, 0))
        ttk.Button(
            bindings_btns, text="HID key reference…",
            command=self._open_hid_reference,
        ).pack(side="left", padx=(6, 0))
        ttk.Button(
            bindings_btns, text="Remap by click…",
            command=self._open_remap_dialog,
        ).pack(side="left", padx=(6, 0))
        ttk.Button(
            bindings_btns, text="Identify & label…",
            command=self._open_identify_dialog,
        ).pack(side="left", padx=(6, 0))

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

    # Tk event.num (Windows) → Razer button number. Standard mapping; mouse
    # vendor can diverge, but this covers the usual left/middle/right/x1/x2.
    _TK_TO_RAZER = {1: 1, 2: 3, 3: 2, 4: 4, 5: 5}

    def _mouse_btn_for_hid(self, hid: int) -> int | None:
        """Scan current bindings for a mouse button currently emitting this HID
        key. Returns the Razer button id or None. Used to resolve keyboard
        events back to 'oh that was mouse button N' in the live log."""
        if not hasattr(self, "tree"):
            return None
        marker = f"HID 0x{hid:02x}"
        for item in self.tree.get_children():
            vals = self.tree.item(item, "values")
            # vals = (id, type, summary, raw) — summary contains "HID 0xNN (NAME)"
            if len(vals) >= 3 and marker in str(vals[2]):
                try:
                    return int(vals[0])
                except ValueError:
                    pass
        return None

    def _on_key(self, event) -> str:
        hid = vk_to_hid(event.keycode & 0xFF)
        hid_part = f"HID 0x{hid:02x} ({hid_name(hid)})" if hid is not None else "no HID mapping"
        mouse_btn = self._mouse_btn_for_hid(hid) if hid is not None else None
        if mouse_btn is not None:
            label = self.labels.get(mouse_btn, "")
            source = f"  → mouse btn {mouse_btn}" + (f" ({label})" if label else "")
        else:
            source = ""
        self._log("KEY", f"keysym={event.keysym!r:12s}  {hid_part}{source}")
        if self.capture_var.get():
            self.payload_var.set(f"{event.keycode & 0xFF:02x}")
            self.action_var.set("keyboard")
            self.capture_var.set(False)
            self._status(f"Captured keycode 0x{event.keycode & 0xFF:02x} into payload.")
        return "break"

    def _on_mouse(self, event) -> None:
        razer = self._TK_TO_RAZER.get(event.num)
        if razer is not None:
            label = self.labels.get(razer, "")
            source = f"  → mouse btn {razer}" + (f" ({label})" if label else "")
        else:
            source = ""
        self._log("MOUSE", f"tk_button={event.num}{source}  x={event.x} y={event.y}")

    def _on_wheel(self, event) -> None:
        self._log("WHEEL", f"delta={event.delta}")

    def _clear_log(self) -> None:
        self.log_text.delete("1.0", "end")

    # ---- bindings table ----

    # Razer firmware holds up to 5 onboard profiles (0-4). Synapse-era mappings
    # often survived in a non-zero profile after uninstall while profile 0 was
    # wiped. We scan every profile and surface the first one that returns a
    # real mapping for each button id.
    PROFILES_TO_SCAN = (0, 1, 2, 3, 4)

    def _reload_bindings(self) -> None:
        self._status("Reading bindings across profiles 0-4…")
        for r in self.tree.get_children():
            self.tree.delete(r)

        def work():
            rows: list[tuple[int, int | None, "ButtonAction | str"]] = []
            with RazerTransport(self.device) as t:
                m = RazerMouse(t)
                for bid in self.BTN_IDS_TO_SCAN:
                    found = None
                    first_err = None
                    for prof in self.PROFILES_TO_SCAN:
                        try:
                            action = m.get_button_action(button_id=bid, profile=prof)
                        except Exception as e:
                            if first_err is None:
                                first_err = str(e)
                            continue
                        # "failed: device returned status 0x03" shows up as a successful
                        # call but an empty/unmapped summary. mouse.py raises for those,
                        # so if we're here the mapping is real for this profile.
                        found = (prof, action)
                        break
                    if found:
                        prof, action = found
                        rows.append((bid, prof, action))
                    else:
                        rows.append((bid, None, first_err or "unmapped on profiles 0-4"))
            self.after(0, lambda: self._render_bindings(rows))

        threading.Thread(target=work, daemon=True).start()

    def _render_bindings(self, rows) -> None:
        for bid, prof, payload in rows:
            label = self.labels.get(bid, "")
            label_suffix = f"  —  {label}" if label else ""
            if isinstance(payload, ButtonAction):
                type_name = {
                    BTN_ACTION_DEFAULT: "default", BTN_ACTION_KEYBOARD: "keyboard",
                    BTN_ACTION_DISABLE: "disabled",
                }.get(payload.action_type, f"0x{payload.action_type:02x}")
                summary = payload.summary if prof == 0 else f"{payload.summary}   [profile {prof}]"
                self.tree.insert("", "end",
                                 values=(payload.button_id, type_name, summary + label_suffix, payload.payload.hex()))
            else:
                self.tree.insert("", "end", values=(bid, "-", str(payload) + label_suffix, ""))
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

    def _open_identify_dialog(self) -> None:
        """Walk physical buttons on the mouse, press each one, label what it
        is. Mouse events resolve directly via Tk event.num → Razer id. Key
        events resolve via the HID → button lookup against the bindings table.
        Labels persist per-device via button_labels.json."""
        _d = getattr(self.parent_gui, "_dark",
                     {"bg": "white", "fg": "black", "field": "white", "select": "#00ffff", "active": "#3c3c3c"})

        modal = tk.Toplevel(self)
        modal.title("Identify & label buttons")
        modal.geometry("640x560")
        modal.transient(self)
        modal.grab_set()
        modal.configure(bg=_d["bg"])

        wrap = ttk.Frame(modal, padding=PADDING)
        wrap.pack(fill="both", expand=True)

        # Capture area
        cap_frame = tk.Frame(wrap, bg=_d["field"], height=70)
        cap_frame.pack(fill="x", pady=(0, 6))
        cap_frame.pack_propagate(False)
        cap_prompt = tk.Label(
            cap_frame, text="PRESS A PHYSICAL BUTTON ON THE MOUSE",
            bg=_d["field"], fg=_d["fg"], font=("Segoe UI", 11, "bold"),
        )
        cap_prompt.pack(expand=True)
        cap_status = ttk.Label(wrap, text="— waiting —", foreground=_d.get("select", "#00ffff"))
        cap_status.pack(anchor="w", pady=(0, 10))

        # Table: ID | Current binding | Label (editable via click)
        table_frame = ttk.LabelFrame(wrap, text="Button labels (click Label column to edit)", padding=PADDING)
        table_frame.pack(fill="both", expand=True)
        cols = ("id", "binding", "label")
        tree = ttk.Treeview(table_frame, columns=cols, show="headings", height=14)
        tree.heading("id", text="ID")
        tree.heading("binding", text="CURRENT BINDING")
        tree.heading("label", text="LABEL")
        tree.column("id", width=50, anchor="center")
        tree.column("binding", width=260, anchor="w")
        tree.column("label", width=260, anchor="w")
        tree.pack(fill="both", expand=True)

        # Mirror the main bindings table's rows (id + binding summary) + labels
        working_labels = dict(self.labels)

        def refresh_table():
            for row in tree.get_children():
                tree.delete(row)
            for item in self.tree.get_children():
                vals = self.tree.item(item, "values")
                try:
                    bid = int(vals[0])
                except (ValueError, IndexError):
                    continue
                binding = str(vals[2]) if len(vals) >= 3 else ""
                label = working_labels.get(bid, "")
                tree.insert("", "end", iid=str(bid), values=(bid, binding, label))

        refresh_table()

        def edit_label(event):
            region = tree.identify_region(event.x, event.y)
            if region != "cell":
                return
            col = tree.identify_column(event.x)
            if col != "#3":  # the "label" column
                return
            item = tree.identify_row(event.y)
            if not item:
                return
            bid = int(item)
            x, y, w, h = tree.bbox(item, col)
            entry = ttk.Entry(tree)
            entry.insert(0, working_labels.get(bid, ""))
            entry.place(x=x, y=y, width=w, height=h)
            entry.focus_set()
            entry.select_range(0, "end")
            def commit(_evt=None):
                working_labels[bid] = entry.get().strip()
                entry.destroy()
                refresh_table()
                tree.selection_set(str(bid))
            entry.bind("<Return>", commit)
            entry.bind("<Escape>", lambda e: entry.destroy())
            entry.bind("<FocusOut>", commit)
        tree.bind("<Double-Button-1>", edit_label)

        def set_capture_result(bid: int | None, detail: str):
            if bid is None:
                cap_status.config(text=f"Captured: {detail} — couldn't resolve to a Razer button id")
                return
            tree.selection_set(str(bid))
            tree.see(str(bid))
            cap_status.config(text=f"Captured: {detail} → button ID {bid}. Double-click the Label cell to name it.")

        def on_mouse(event):
            razer = self._TK_TO_RAZER.get(event.num)
            set_capture_result(razer, f"mouse tk_button={event.num}")
        def on_key(event):
            if event.keysym == "Escape":
                modal.destroy()
                return "break"
            hid = vk_to_hid(event.keycode & 0xFF)
            if hid is None:
                set_capture_result(None, f"key '{event.keysym}' (VK 0x{event.keycode & 0xFF:02x})")
                return "break"
            bid = self._mouse_btn_for_hid(hid)
            set_capture_result(bid, f"key '{event.keysym}' = HID 0x{hid:02x} ({hid_name(hid)})")
            return "break"

        cap_frame.bind("<Button>", on_mouse)
        cap_prompt.bind("<Button>", on_mouse)
        modal.bind("<KeyPress>", on_key)

        # Action buttons
        btns = ttk.Frame(wrap)
        btns.pack(fill="x", pady=(10, 0))
        def do_save():
            self.labels = {k: v for k, v in working_labels.items() if v.strip()}
            try:
                button_labels.save_for(self.device, self.labels)
            except Exception as e:
                messagebox.showerror("Save failed", str(e), parent=modal)
                return
            modal.destroy()
            self._reload_bindings()  # re-render so labels appear in main table
            self._status(f"Saved {len(self.labels)} button label(s).")
        ttk.Button(btns, text="Save labels", command=do_save).pack(side="right")
        ttk.Button(btns, text="Cancel", command=modal.destroy).pack(side="right", padx=(0, 6))

        modal.focus_set()

    def _open_remap_dialog(self) -> None:
        """Two-step remap: (1) click the mouse button, (2) press the keyboard key,
        (3) Save. Mouse-click detection covers buttons currently bound to default
        mouse actions (1-5 directly, 6-11 if remapped to default mouse). A manual
        dropdown is the fallback for buttons that are currently keyboard-bound or
        unmapped (they don't emit mouse events when clicked)."""
        _d = getattr(self.parent_gui, "_dark", {"bg": "white", "fg": "black", "field": "white", "select": "#00ffff", "active": "#3c3c3c"})

        # Tk event.num (Windows) → Razer button number. Standard mapping for
        # mice that follow the convention: left=1, right=2, middle=3 (Razer
        # numbering), with X1/X2 as back/forward.
        TK_TO_RAZER = {1: 1, 2: 3, 3: 2, 4: 4, 5: 5}

        modal = tk.Toplevel(self)
        modal.title("Remap button")
        modal.geometry("540x480")
        modal.transient(self)
        modal.grab_set()
        modal.configure(bg=_d["bg"])

        wrap = ttk.Frame(modal, padding=PADDING)
        wrap.pack(fill="both", expand=True)

        state = {"bid": None, "hid": None, "hid_label": None}

        # ---- Step 1 ----
        s1 = ttk.LabelFrame(wrap, text="Step 1 — which button?", padding=PADDING)
        s1.pack(fill="x", pady=(0, 10))
        s1_target = tk.Frame(s1, bg=_d["field"], height=70)
        s1_target.pack(fill="x")
        s1_target.pack_propagate(False)
        s1_prompt = tk.Label(
            s1_target, text="CLICK HERE WITH THE MOUSE BUTTON",
            bg=_d["field"], fg=_d["fg"], font=("Segoe UI", 11, "bold"),
        )
        s1_prompt.pack(expand=True)

        s1_manual = ttk.Frame(s1)
        s1_manual.pack(fill="x", pady=(6, 0))
        ttk.Label(s1_manual, text="or pick manually:").pack(side="left")
        manual_var = tk.IntVar(value=0)
        manual_combo = ttk.Combobox(
            s1_manual, textvariable=manual_var, width=5, state="readonly",
            values=[0] + self.BTN_IDS_TO_SCAN,
        )
        manual_combo.pack(side="left", padx=(6, 0))
        s1_status = ttk.Label(s1, text="— no button selected yet —", foreground=_d.get("select", "#00ffff"))
        s1_status.pack(anchor="w", pady=(6, 0))

        # ---- Step 2 ----
        s2 = ttk.LabelFrame(wrap, text="Step 2 — what should it do?", padding=PADDING)
        s2.pack(fill="x", pady=(0, 10))
        s2_target = tk.Frame(s2, bg=_d["field"], height=70)
        s2_target.pack(fill="x")
        s2_target.pack_propagate(False)
        s2_prompt = tk.Label(
            s2_target, text="PRESS THE KEYBOARD KEY",
            bg=_d["field"], fg=_d["fg"], font=("Segoe UI", 11, "bold"),
        )
        s2_prompt.pack(expand=True)
        s2_status = ttk.Label(s2, text="— no key pressed yet —", foreground=_d.get("select", "#00ffff"))
        s2_status.pack(anchor="w", pady=(6, 0))

        # ---- Buttons ----
        btn_row = ttk.Frame(wrap)
        btn_row.pack(fill="x", pady=(14, 0))
        save_btn = ttk.Button(btn_row, text="Save to mouse", state="disabled")
        save_btn.pack(side="right")
        ttk.Button(btn_row, text="Cancel", command=modal.destroy).pack(side="right", padx=(0, 6))

        def refresh_save():
            if state["bid"] is not None and state["hid"] is not None:
                save_btn.state(["!disabled"])
            else:
                save_btn.state(["disabled"])

        def current_binding_summary(bid: int) -> str:
            for item in self.tree.get_children():
                vals = self.tree.item(item, "values")
                try:
                    if int(vals[0]) == bid:
                        return f"currently: {vals[2]}"
                except (ValueError, IndexError):
                    pass
            return "currently: (unknown)"

        def set_button(bid: int):
            state["bid"] = bid
            manual_var.set(bid)
            s1_status.config(text=f"✓ Button {bid}  —  {current_binding_summary(bid)}")
            refresh_save()

        # Step 1 — mouse click inside the target frame
        def on_s1_click(event):
            bid = TK_TO_RAZER.get(event.num)
            if bid is None:
                s1_status.config(text=f"✗ Tk button {event.num} has no Razer mapping — use manual picker")
                return
            set_button(bid)
        s1_target.bind("<Button>", on_s1_click)
        s1_prompt.bind("<Button>", on_s1_click)

        # Manual dropdown fallback
        def on_manual(_):
            try:
                bid = int(manual_var.get())
            except (tk.TclError, ValueError):
                return
            if bid > 0:
                set_button(bid)
        manual_combo.bind("<<ComboboxSelected>>", on_manual)

        # Step 2 — key press anywhere in modal (but intercepted by step 2 target first)
        def on_s2_key(event):
            if event.keysym == "Escape":
                modal.destroy()
                return "break"
            hid = vk_to_hid(event.keycode & 0xFF)
            if hid is None:
                s2_status.config(text=f"✗ '{event.keysym}' (VK 0x{event.keycode & 0xFF:02x}) has no HID mapping — try another")
                state["hid"] = None
                refresh_save()
                return "break"
            state["hid"] = hid
            state["hid_label"] = hid_name(hid)
            s2_status.config(text=f"✓ Will send: {state['hid_label']}   (HID 0x{hid:02x})")
            refresh_save()
            return "break"
        # Bind key capture on the modal so focus doesn't matter
        modal.bind("<KeyPress>", on_s2_key)

        # Save
        def do_save():
            bid = state["bid"]
            hid = state["hid"]
            if bid is None or hid is None:
                return
            label = state["hid_label"]
            modal.destroy()
            self._status(f"Writing btn {bid} = {label} (HID 0x{hid:02x})…")

            def work():
                try:
                    with RazerTransport(self.device) as t:
                        m = RazerMouse(t)
                        m.set_button_action(
                            button_id=bid, action_type=BTN_ACTION_KEYBOARD,
                            payload=bytes([0x00, hid, 0x00, 0x00]), sub_type=0x02, profile=0,
                        )
                        after = m.get_button_action(button_id=bid, profile=0)
                except Exception as e:
                    self.after(0, lambda: self._status(f"Remap failed: {e}"))
                    return
                self.after(0, lambda: self._status(f"Remapped btn {bid} → {label}. Read-back: {after.summary}"))
                self.after(0, self._reload_bindings)
            threading.Thread(target=work, daemon=True).start()

        save_btn.config(command=do_save)
        modal.focus_set()

    def _open_hid_reference(self) -> None:
        """Scrollable reference of HID Usage IDs → key names. Read-only."""
        modal = tk.Toplevel(self)
        modal.title("HID key reference")
        modal.geometry("480x560")
        modal.transient(self)

        wrap = ttk.Frame(modal, padding=PADDING)
        wrap.pack(fill="both", expand=True)

        ttk.Label(
            wrap,
            text="USB HID Keyboard Usage IDs — the mouse firmware stores keyboard\n"
                 "bindings using these codes, not Windows virtual-key codes.",
        ).pack(anchor="w", pady=(0, 8))

        cols = ("hid", "key")
        tree = ttk.Treeview(wrap, columns=cols, show="headings", height=22)
        tree.heading("hid", text="HID")
        tree.heading("key", text="KEY")
        tree.column("hid", width=90, anchor="w")
        tree.column("key", width=340, anchor="w")
        tree.pack(fill="both", expand=True)

        for code in sorted(HID_NAMES):
            tree.insert("", "end", values=(f"0x{code:02x}  ({code})", HID_NAMES[code]))

        ttk.Button(wrap, text="Close", command=modal.destroy).pack(anchor="e", pady=(8, 0))

    def _open_rebind_modal(self) -> None:
        """One-step rebind: select a row, click, press the key you want. Writes
        a keyboard-action binding using the same code path as the manual form."""
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("Select a button first",
                                "Click a row in the bindings table, then click this again.",
                                parent=self)
            return
        try:
            bid = int(self.tree.item(sel[0], "values")[0])
        except (ValueError, IndexError):
            messagebox.showerror("Bad selection", "Couldn't read the button ID from that row.", parent=self)
            return

        _d = getattr(self.parent_gui, "_dark", {"bg": "white", "fg": "black", "field": "white", "select": "#3c3c3c"})

        modal = tk.Toplevel(self)
        modal.title(f"Rebind button {bid}")
        modal.geometry("420x210")
        modal.transient(self)
        modal.grab_set()
        modal.configure(bg=_d["bg"])

        wrap = ttk.Frame(modal, padding=PADDING)
        wrap.pack(fill="both", expand=True)

        ttk.Label(
            wrap, text=f"Rebind mouse button {bid}",
            font=("Segoe UI", 11, "bold"),
        ).pack(anchor="w")
        ttk.Label(
            wrap, text="Press the key you want this button to send.\nEsc to cancel.",
        ).pack(anchor="w", pady=(4, 10))

        captured_label = ttk.Label(wrap, text="— no key pressed yet —", foreground=_d.get("select", "#00ffff"))
        captured_label.pack(anchor="w")

        state = {"code": None, "label": None}

        def on_key(event):
            if event.keysym == "Escape":
                modal.destroy()
                return "break"
            # Tk's event.keycode on Windows is the Virtual-Key code — mouse
            # firmware stores HID Usage IDs. These are different. Translate.
            hid = vk_to_hid(event.keycode & 0xFF)
            if hid is None:
                captured_label.config(
                    text=f"'{event.keysym}' (VK 0x{event.keycode & 0xFF:02x}) — no HID mapping; try another key",
                )
                write_btn.state(["disabled"])
                return "break"
            state["code"] = hid
            state["label"] = hid_name(hid)
            captured_label.config(text=f"You pressed: {state['label']}   (HID 0x{hid:02x})")
            write_btn.state(["!disabled"])
            return "break"

        def do_write():
            if state["code"] is None:
                return
            code = state["code"]
            label = state["label"]
            modal.destroy()
            self._status(f"Writing btn {bid} = {label} (0x{code:02x})…")

            def work():
                try:
                    with RazerTransport(self.device) as t:
                        m = RazerMouse(t)
                        m.set_button_action(
                            button_id=bid, action_type=BTN_ACTION_KEYBOARD,
                            payload=bytes([0x00, code, 0x00, 0x00]), sub_type=0x02, profile=0,
                        )
                        after = m.get_button_action(button_id=bid, profile=0)
                except Exception as e:
                    self.after(0, lambda: self._status(f"Rebind failed: {e}"))
                    return
                self.after(0, lambda: self._status(f"Rebound btn {bid} → {label}. Read-back: {after.summary}"))
                self.after(0, self._reload_bindings)

            threading.Thread(target=work, daemon=True).start()

        btn_row = ttk.Frame(wrap)
        btn_row.pack(fill="x", pady=(14, 0))
        write_btn = ttk.Button(btn_row, text="Write to mouse", command=do_write)
        write_btn.pack(side="right")
        write_btn.state(["disabled"])
        ttk.Button(btn_row, text="Cancel", command=modal.destroy).pack(side="right", padx=(0, 6))

        modal.bind("<KeyPress>", on_key)
        modal.focus_set()

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
