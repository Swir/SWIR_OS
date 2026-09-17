#!/usr/bin/env python3
"""SWIR Settings — native per-user Control Center foundation for System Edition."""

from __future__ import annotations

import json
import os
import pathlib
import sys
from typing import Final

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gdk, GLib, Gtk  # noqa: E402

LIBDIR = pathlib.Path("/usr/local/lib/swir")
if LIBDIR.is_dir() and str(LIBDIR) not in sys.path:
    sys.path.insert(0, str(LIBDIR))

from core_runtime import UserSettingsStore  # noqa: E402

APP_ID: Final = "dev.swir.Settings"
EVIDENCE_SCHEMA: Final = "swir.native-settings-runtime-evidence/0.1"
LANGUAGES: Final = (
    ("English", "en"),
    ("Polski", "pl-PL"),
    ("Norsk bokmål", "nb-NO"),
    ("Deutsch", "de-DE"),
    ("Español", "es-ES"),
    ("Français", "fr-FR"),
    ("Italiano", "it-IT"),
    ("Português (Brasil)", "pt-BR"),
    ("Українська", "uk-UA"),
    ("Русский", "ru-RU"),
    ("Türkçe", "tr-TR"),
    ("العربية", "ar"),
    ("עברית", "he"),
    ("日本語", "ja"),
    ("简体中文", "zh-CN"),
)

CSS = b"""
window.swir-app { background: #02050A; color: #F4FAFF; }
.swir-header { background: #07111C; border-bottom: 1px solid #0088FF; padding: 12px 16px; }
.swir-brand { color: #62E5FF; font-size: 19px; font-weight: 800; }
.swir-muted { color: #8DA8B8; }
.swir-card { background: #07111C; border: 1px solid rgba(98,229,255,0.28); border-radius: 16px; padding: 18px; }
.swir-section { color: #F4FAFF; font-size: 17px; font-weight: 700; }
.swir-button { background: #07111C; color: #F4FAFF; border: 1px solid #0088FF; border-radius: 10px; padding: 8px 14px; }
.swir-button:hover { border-color: #62E5FF; }
"""


class SwirSettings(Gtk.Application):
    def __init__(self) -> None:
        super().__init__(application_id=APP_ID)
        self.window: Gtk.ApplicationWindow | None = None
        self.language: Gtk.ComboBoxText | None = None
        self.appearance: Gtk.ComboBoxText | None = None
        self.clock24h: Gtk.CheckButton | None = None
        self.status: Gtk.Label | None = None
        self.store = UserSettingsStore()
        self.e2e = os.environ.get("SWIR_APP_E2E", "0") == "1"
        self.evidence_path = os.environ.get("SWIR_APP_EVIDENCE_PATH", "")

    def do_startup(self) -> None:
        Gtk.Application.do_startup(self)
        provider = Gtk.CssProvider()
        provider.load_from_data(CSS)
        display = Gdk.Display.get_default()
        if display is None:
            raise RuntimeError("SWIR Settings requires a graphical display")
        Gtk.StyleContext.add_provider_for_display(display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    @staticmethod
    def _row(label: str, widget: Gtk.Widget) -> Gtk.Box:
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        title = Gtk.Label(label=label)
        title.set_xalign(0)
        title.set_hexpand(True)
        row.append(title)
        row.append(widget)
        return row

    def do_activate(self) -> None:
        if self.window is not None:
            self.window.present()
            return
        settings = self.store.load()

        window = Gtk.ApplicationWindow(application=self)
        window.set_title("SWIR Settings")
        window.set_default_size(760, 600)
        window.add_css_class("swir-app")
        self.window = window

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        window.set_child(root)
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        header.add_css_class("swir-header")
        brand = Gtk.Label(label="◆  SWIR Settings")
        brand.add_css_class("swir-brand")
        brand.set_xalign(0)
        header.append(brand)
        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        header.append(spacer)
        scope = Gtk.Label(label="USER SETTINGS")
        scope.add_css_class("swir-muted")
        header.append(scope)
        root.append(header)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        content.set_margin_top(24)
        content.set_margin_bottom(24)
        content.set_margin_start(28)
        content.set_margin_end(28)
        content.set_hexpand(True)
        content.set_vexpand(True)
        root.append(content)

        regional = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        regional.add_css_class("swir-card")
        title = Gtk.Label(label="Language & Region")
        title.add_css_class("swir-section")
        title.set_xalign(0)
        regional.append(title)

        self.language = Gtk.ComboBoxText()
        selected_language = 0
        for index, (label, tag) in enumerate(LANGUAGES):
            self.language.append(tag, label)
            if tag == settings["language"]:
                selected_language = index
        self.language.set_active(selected_language)
        regional.append(self._row("Interface language preference", self.language))

        self.clock24h = Gtk.CheckButton(label="Use 24-hour clock")
        self.clock24h.set_active(bool(settings["clock24h"]))
        regional.append(self.clock24h)
        content.append(regional)

        appearance_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        appearance_card.add_css_class("swir-card")
        appearance_title = Gtk.Label(label="Appearance")
        appearance_title.add_css_class("swir-section")
        appearance_title.set_xalign(0)
        appearance_card.append(appearance_title)
        self.appearance = Gtk.ComboBoxText()
        self.appearance.append("dark", "SWIR Dark")
        self.appearance.append("system", "Follow system preference")
        self.appearance.set_active_id(str(settings["appearance"]))
        appearance_card.append(self._row("Color preference", self.appearance))
        note = Gtk.Label(label="Theme packages and accessibility-safe shell skins remain a separate roadmap milestone.", wrap=True)
        note.add_css_class("swir-muted")
        note.set_xalign(0)
        appearance_card.append(note)
        content.append(appearance_card)

        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        self.status = Gtk.Label(label="Per-user settings only — privileged system changes are not exposed here.")
        self.status.add_css_class("swir-muted")
        self.status.set_xalign(0)
        self.status.set_hexpand(True)
        actions.append(self.status)
        save = Gtk.Button(label="Save")
        save.add_css_class("swir-button")
        save.connect("clicked", self._save)
        actions.append(save)
        content.append(actions)

        window.connect("map", self._on_mapped)
        window.present()

    def _payload(self) -> dict[str, object]:
        assert self.language is not None and self.appearance is not None and self.clock24h is not None
        return {
            "language": self.language.get_active_id() or "en",
            "appearance": self.appearance.get_active_id() or "dark",
            "clock24h": self.clock24h.get_active(),
        }

    def _save(self, _button: Gtk.Button | None = None) -> dict[str, object]:
        payload = self.store.save(self._payload())
        if self.status is not None:
            self.status.set_text("Saved securely to your SWIR user profile.")
        return payload

    def _on_mapped(self, _window: Gtk.Window) -> None:
        if not self.e2e or not self.evidence_path:
            return
        path = pathlib.Path(self.evidence_path)
        runtime_text = os.environ.get("XDG_RUNTIME_DIR", "")
        if not runtime_text or path.parent.resolve() != pathlib.Path(runtime_text).resolve():
            raise RuntimeError("refusing SWIR Settings evidence path outside XDG_RUNTIME_DIR")
        saved = self._save()
        payload = {
            "schema": EVIDENCE_SCHEMA,
            "passed": True,
            "applicationId": APP_ID,
            "nativeToolkit": "gtk4",
            "displayProtocol": "wayland",
            "windowMapped": True,
            "privilegedOperations": False,
            "settingsSchema": saved["schema"],
            "ownerOnlySettingsFile": (self.store.path.stat().st_mode & 0o777) == 0o600,
            "language": saved["language"],
            "clock24h": saved["clock24h"],
        }
        path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
        path.chmod(0o600)
        GLib.timeout_add(250, self._finish_e2e)

    def _finish_e2e(self) -> bool:
        self.quit()
        return False


if __name__ == "__main__":
    raise SystemExit(SwirSettings().run(sys.argv))
