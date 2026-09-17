#!/usr/bin/env python3
"""Native GTK4 shell surface for SWIR OS System Edition.

This process is intentionally unprivileged. It presents the desktop surface,
status/header area and a small allowlisted launcher. Privileged system actions
remain behind their dedicated brokers/polkit policies.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import pathlib
import shutil
import subprocess
import sys
from typing import Final

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import GLib, Gtk  # noqa: E402

APP_ID: Final = "dev.swir.Shell"
EVIDENCE_SCHEMA: Final = "swir.native-shell-runtime-evidence/0.1"

CSS = b"""
window.swir-shell {
  background: #02050A;
  color: #EAF9FF;
}
.swir-topbar {
  background: rgba(7,17,28,0.97);
  border-bottom: 1px solid #0088FF;
  padding: 12px 18px;
}
.swir-brand { color: #62E5FF; font-size: 20px; font-weight: 800; }
.swir-subtle { color: #8FAFC2; }
.swir-title { color: #FFFFFF; font-size: 34px; font-weight: 800; }
.swir-card {
  background: rgba(7,17,28,0.92);
  border: 1px solid rgba(98,229,255,0.32);
  border-radius: 18px;
  padding: 22px;
}
.swir-launcher {
  background: #07111C;
  color: #EAF9FF;
  border: 1px solid #0088FF;
  border-radius: 14px;
  padding: 12px 16px;
}
.swir-launcher:hover { background: #0A2136; border-color: #62E5FF; }
.swir-dock {
  background: rgba(7,17,28,0.97);
  border-top: 1px solid rgba(98,229,255,0.35);
  padding: 12px 18px;
}
"""

# Fixed commands only: user-controlled strings are never passed to a shell.
LAUNCHERS: Final = (
    ("Files", (("/usr/bin/nautilus",), ("/usr/bin/thunar",), ("/usr/bin/pcmanfm",))),
    ("Terminal", (("/usr/bin/foot",), ("/usr/bin/kitty",), ("/usr/bin/gnome-terminal",))),
    ("Settings", (("/usr/local/bin/swir-settings",), ("/usr/bin/gnome-control-center",))),
    ("Install SWIR OS", (("/usr/local/bin/swir-installer",),)),
)


class SwirShell(Gtk.Application):
    def __init__(self) -> None:
        super().__init__(application_id=APP_ID)
        self.clock_label: Gtk.Label | None = None
        self.status_label: Gtk.Label | None = None
        self.window: Gtk.ApplicationWindow | None = None
        self.evidence_path = os.environ.get("SWIR_SHELL_EVIDENCE_PATH", "")
        self.evidence_written = False

    def do_startup(self) -> None:
        Gtk.Application.do_startup(self)
        provider = Gtk.CssProvider()
        provider.load_from_data(CSS)
        display = __import__("gi.repository", fromlist=["Gdk"]).Gdk.Display.get_default()
        if display is not None:
            Gtk.StyleContext.add_provider_for_display(
                display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
            )

    def do_activate(self) -> None:
        if self.window is not None:
            self.window.present()
            return

        window = Gtk.ApplicationWindow(application=self)
        window.set_title("SWIR OS")
        window.set_default_size(1280, 720)
        window.add_css_class("swir-shell")
        window.fullscreen()
        self.window = window

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        window.set_child(root)

        top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        top.add_css_class("swir-topbar")
        brand = Gtk.Label(label="◆  SWIR OS")
        brand.add_css_class("swir-brand")
        brand.set_xalign(0)
        top.append(brand)
        edition = Gtk.Label(label="SYSTEM EDITION")
        edition.add_css_class("swir-subtle")
        top.append(edition)
        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        top.append(spacer)
        self.clock_label = Gtk.Label()
        self.clock_label.add_css_class("swir-brand")
        top.append(self.clock_label)
        root.append(top)

        center = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=22)
        center.set_hexpand(True)
        center.set_vexpand(True)
        center.set_halign(Gtk.Align.CENTER)
        center.set_valign(Gtk.Align.CENTER)

        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        card.add_css_class("swir-card")
        card.set_size_request(650, -1)
        title = Gtk.Label(label="Welcome to SWIR OS")
        title.add_css_class("swir-title")
        title.set_xalign(0)
        card.append(title)
        detail = Gtk.Label(
            label="Native Linux desktop session • Debian 13 foundation • Wayland",
            wrap=True,
        )
        detail.add_css_class("swir-subtle")
        detail.set_xalign(0)
        card.append(detail)
        self.status_label = Gtk.Label(label="Ready")
        self.status_label.set_xalign(0)
        card.append(self.status_label)
        center.append(card)
        root.append(center)

        dock = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        dock.add_css_class("swir-dock")
        dock.set_halign(Gtk.Align.CENTER)
        for label, candidates in LAUNCHERS:
            button = Gtk.Button(label=label)
            button.add_css_class("swir-launcher")
            button.connect("clicked", self._launch, label, candidates)
            dock.append(button)
        root.append(dock)

        GLib.timeout_add_seconds(1, self._update_clock)
        self._update_clock()
        window.connect("map", self._on_mapped)
        window.present()

    def _update_clock(self) -> bool:
        if self.clock_label is not None:
            self.clock_label.set_text(dt.datetime.now().astimezone().strftime("%H:%M"))
        return True

    def _launch(self, _button: Gtk.Button, label: str, candidates: tuple[tuple[str, ...], ...]) -> None:
        command = next((candidate for candidate in candidates if pathlib.Path(candidate[0]).is_file()), None)
        if command is None:
            if self.status_label is not None:
                self.status_label.set_text(f"{label} is not installed in this image yet.")
            return
        try:
            subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=True,
                start_new_session=True,
            )
            if self.status_label is not None:
                self.status_label.set_text(f"Opened {label}")
        except OSError as exc:
            if self.status_label is not None:
                self.status_label.set_text(f"Could not open {label}: {exc.strerror or 'launch failed'}")

    def _on_mapped(self, _window: Gtk.Window) -> None:
        if self.evidence_written or not self.evidence_path:
            return
        path = pathlib.Path(self.evidence_path)
        runtime = pathlib.Path(os.environ.get("XDG_RUNTIME_DIR", ""))
        if not runtime or path.parent != runtime:
            print("refusing shell evidence path outside XDG_RUNTIME_DIR", file=sys.stderr)
            return
        payload = {
            "schema": EVIDENCE_SCHEMA,
            "passed": True,
            "applicationId": APP_ID,
            "nativeToolkit": "gtk4",
            "displayProtocol": "wayland",
            "windowMapped": True,
            "fullscreenRequested": True,
            "launcherEntries": [item[0] for item in LAUNCHERS],
            "privilegedOperationsInShell": False,
        }
        path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
        path.chmod(0o600)
        self.evidence_written = True


if __name__ == "__main__":
    raise SystemExit(SwirShell().run(sys.argv))
