#!/usr/bin/env python3
"""SWIR Network Center — native read-only NetworkManager status surface."""

from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
from dataclasses import dataclass
from typing import Final, Mapping

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gdk, GLib, Gtk  # noqa: E402

LIBDIR = pathlib.Path("/usr/local/lib/swir")
if LIBDIR.is_dir() and str(LIBDIR) not in sys.path:
    sys.path.insert(0, str(LIBDIR))

from core_runtime import UserSettingsStore, normalize_language_tag  # noqa: E402

APP_ID: Final = "dev.swir.NetworkCenter"
EVIDENCE_SCHEMA: Final = "swir.native-network-center-runtime-evidence/0.2"
NMCLI: Final = pathlib.Path("/usr/bin/nmcli")
QUERY_TIMEOUT_SECONDS: Final = 4
MAX_DEVICE_ROWS: Final = 100

CSS = b"""
window.swir-app { background: #02050A; color: #F4FAFF; }
.swir-header { background: #07111C; border-bottom: 1px solid #0088FF; padding: 10px 14px; }
.swir-brand { color: #62E5FF; font-size: 18px; font-weight: 800; }
.swir-muted { color: #8DA8B8; }
.swir-state { background: #07111C; border: 1px solid rgba(98,229,255,0.28); border-radius: 12px; padding: 10px 14px; }
.swir-row { padding: 8px 10px; border-bottom: 1px solid rgba(98,229,255,0.08); }
.swir-button { background: #07111C; color: #F4FAFF; border: 1px solid #0088FF; border-radius: 10px; padding: 7px 12px; }
.swir-button:hover { border-color: #62E5FF; }
"""

_TRANSLATIONS: Final[Mapping[str, Mapping[str, str]]] = {
    "en": {
        "window_title": "SWIR Network Center",
        "brand": "◆  SWIR Network Center",
        "refresh": "Refresh",
        "footer": "Read-only status • connection changes remain behind dedicated policy/broker work",
        "manager_status": "NetworkManager: {state}",
        "manager_unavailable": "NetworkManager status unavailable: {state}",
        "device_unavailable": "Device status unavailable: {reason}",
        "refresh_tooltip": "Refresh read-only network status",
        "devices_tooltip": "Network devices reported by NetworkManager",
    },
    "pl-PL": {
        "window_title": "Centrum sieci SWIR",
        "brand": "◆  Centrum sieci SWIR",
        "refresh": "Odśwież",
        "footer": "Status tylko do odczytu • zmiany połączeń pozostają za dedykowaną polityką i brokerem",
        "manager_status": "NetworkManager: {state}",
        "manager_unavailable": "Status NetworkManager jest niedostępny: {state}",
        "device_unavailable": "Status urządzeń jest niedostępny: {reason}",
        "refresh_tooltip": "Odśwież status sieci tylko do odczytu",
        "devices_tooltip": "Urządzenia sieciowe zgłoszone przez NetworkManager",
    },
    "nb-NO": {
        "window_title": "SWIR Nettverkssenter",
        "brand": "◆  SWIR Nettverkssenter",
        "refresh": "Oppdater",
        "footer": "Skrivebeskyttet status • tilkoblingsendringer går fortsatt gjennom egen policy og megler",
        "manager_status": "NetworkManager: {state}",
        "manager_unavailable": "NetworkManager-status er utilgjengelig: {state}",
        "device_unavailable": "Enhetsstatus er utilgjengelig: {reason}",
        "refresh_tooltip": "Oppdater skrivebeskyttet nettverksstatus",
        "devices_tooltip": "Nettverksenheter rapportert av NetworkManager",
    },
}


@dataclass(frozen=True)
class NetworkLocale:
    requested_language: str
    catalog_language: str
    strings: Mapping[str, str]

    @property
    def fallback(self) -> bool:
        return self.requested_language != self.catalog_language

    @property
    def text_direction(self) -> str:
        return "rtl" if self.catalog_language.split("-", 1)[0] in {"ar", "he"} else "ltr"

    def text(self, key: str, **values: object) -> str:
        template = self.strings[key]
        return template.format(**values) if values else template


def network_locale(language: object) -> NetworkLocale:
    requested = normalize_language_tag(language) or "en"
    catalog = requested if requested in _TRANSLATIONS else "en"
    return NetworkLocale(requested, catalog, _TRANSLATIONS[catalog])


@dataclass(frozen=True)
class DeviceRow:
    device: str
    kind: str
    state: str
    connection: str


def _split_nmcli_escaped(line: str) -> list[str]:
    fields: list[str] = []
    buffer: list[str] = []
    escaped = False
    for char in line:
        if escaped:
            buffer.append(char)
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == ":":
            fields.append("".join(buffer))
            buffer.clear()
        else:
            buffer.append(char)
    if escaped:
        buffer.append("\\")
    fields.append("".join(buffer))
    return fields


def _run_nmcli(arguments: tuple[str, ...]) -> tuple[bool, str]:
    if not NMCLI.is_file() or not os.access(NMCLI, os.X_OK):
        return False, "nmcli is not installed"
    try:
        completed = subprocess.run(
            (str(NMCLI), *arguments),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            close_fds=True,
            check=False,
            timeout=QUERY_TIMEOUT_SECONDS,
            env={**os.environ, "LC_ALL": "C"},
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"NetworkManager query failed: {exc}"
    output = completed.stdout.strip()
    if completed.returncode != 0:
        message = completed.stderr.strip() or output or f"nmcli exited with {completed.returncode}"
        return False, message[:500]
    return True, output[:32768]


def read_network_state() -> tuple[str, bool]:
    ok, output = _run_nmcli(("--terse", "--fields", "STATE", "general"))
    if not ok:
        return output, False
    return (output.splitlines()[0].strip() if output else "unknown"), True


def read_devices(limit: int = MAX_DEVICE_ROWS) -> tuple[list[DeviceRow], bool, str]:
    ok, output = _run_nmcli(
        ("--terse", "--escape", "yes", "--fields", "DEVICE,TYPE,STATE,CONNECTION", "device", "status")
    )
    if not ok:
        return [], False, output
    rows: list[DeviceRow] = []
    for line in output.splitlines():
        if not line:
            continue
        parts = _split_nmcli_escaped(line)
        if len(parts) != 4:
            continue
        rows.append(DeviceRow(*(part[:160] for part in parts)))
        if len(rows) >= limit:
            break
    return rows, True, ""


class SwirNetworkCenter(Gtk.Application):
    def __init__(self) -> None:
        super().__init__(application_id=APP_ID)
        self.window: Gtk.ApplicationWindow | None = None
        self.state_label: Gtk.Label | None = None
        self.listbox: Gtk.ListBox | None = None
        self.refresh_button: Gtk.Button | None = None
        self.footer_label: Gtk.Label | None = None
        self.settings_store = UserSettingsStore()
        self.locale = self._load_locale()
        self.e2e = os.environ.get("SWIR_APP_E2E", "0") == "1"
        self.evidence_path = os.environ.get("SWIR_APP_EVIDENCE_PATH", "")
        self.last_nmcli_present = False
        self.last_manager_reachable = False
        self.last_device_query_succeeded = False
        self.last_device_count = 0

    def _load_locale(self) -> NetworkLocale:
        try:
            language = self.settings_store.load().get("language", "en")
        except (OSError, RuntimeError, UnicodeError, ValueError):
            language = "en"
        return network_locale(language)

    def _t(self, key: str, **values: object) -> str:
        return self.locale.text(key, **values)

    def do_startup(self) -> None:
        Gtk.Application.do_startup(self)
        provider = Gtk.CssProvider()
        provider.load_from_data(CSS)
        display = Gdk.Display.get_default()
        if display is None:
            raise RuntimeError("SWIR Network Center requires a graphical display")
        Gtk.StyleContext.add_provider_for_display(display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    def do_activate(self) -> None:
        if self.window is not None:
            self.window.present()
            return

        window = Gtk.ApplicationWindow(application=self)
        window.set_title(self._t("window_title"))
        window.set_default_size(980, 680)
        window.add_css_class("swir-app")
        direction = Gtk.TextDirection.RTL if self.locale.text_direction == "rtl" else Gtk.TextDirection.LTR
        window.set_direction(direction)
        self.window = window

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        window.set_child(root)

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        header.add_css_class("swir-header")
        brand = Gtk.Label(label=self._t("brand"))
        brand.add_css_class("swir-brand")
        brand.set_xalign(0)
        header.append(brand)
        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        header.append(spacer)
        refresh = Gtk.Button(label=self._t("refresh"))
        refresh.add_css_class("swir-button")
        refresh.set_focusable(True)
        refresh.set_tooltip_text(self._t("refresh_tooltip"))
        refresh.connect("clicked", self._refresh_clicked)
        header.append(refresh)
        self.refresh_button = refresh
        root.append(header)

        self.state_label = Gtk.Label()
        self.state_label.add_css_class("swir-state")
        self.state_label.set_xalign(0)
        self.state_label.set_selectable(True)
        root.append(self.state_label)

        scroller = Gtk.ScrolledWindow()
        scroller.set_hexpand(True)
        scroller.set_vexpand(True)
        self.listbox = Gtk.ListBox()
        self.listbox.set_selection_mode(Gtk.SelectionMode.NONE)
        self.listbox.set_tooltip_text(self._t("devices_tooltip"))
        scroller.set_child(self.listbox)
        root.append(scroller)

        footer = Gtk.Label(label=self._t("footer"))
        footer.add_css_class("swir-muted")
        footer.set_xalign(0)
        self.footer_label = footer
        root.append(footer)

        self._refresh()
        window.connect("map", self._on_mapped)
        window.present()

    def _refresh_clicked(self, _button: Gtk.Button) -> None:
        self._refresh()

    def _clear_rows(self) -> None:
        assert self.listbox is not None
        child = self.listbox.get_first_child()
        while child is not None:
            next_child = child.get_next_sibling()
            self.listbox.remove(child)
            child = next_child

    def _refresh(self) -> None:
        assert self.state_label is not None and self.listbox is not None
        self.last_nmcli_present = NMCLI.is_file() and os.access(NMCLI, os.X_OK)
        state, manager_ok = read_network_state()
        devices, device_ok, device_error = read_devices()
        self.last_manager_reachable = manager_ok
        self.last_device_query_succeeded = device_ok
        self.last_device_count = len(devices)

        if manager_ok:
            self.state_label.set_text(self._t("manager_status", state=state))
        else:
            self.state_label.set_text(self._t("manager_unavailable", state=state))

        self._clear_rows()
        if not device_ok:
            row = Gtk.ListBoxRow()
            label = Gtk.Label(label=self._t("device_unavailable", reason=device_error), wrap=True)
            label.set_xalign(0)
            label.add_css_class("swir-muted")
            row.set_child(label)
            self.listbox.append(row)
            return

        for device in devices:
            row = Gtk.ListBoxRow()
            row.add_css_class("swir-row")
            box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
            name = Gtk.Label(label=device.device or "—")
            name.set_xalign(0)
            name.set_width_chars(18)
            box.append(name)
            kind = Gtk.Label(label=device.kind or "—")
            kind.add_css_class("swir-muted")
            kind.set_width_chars(14)
            box.append(kind)
            state_label = Gtk.Label(label=device.state or "—")
            state_label.set_width_chars(20)
            box.append(state_label)
            connection = Gtk.Label(label=device.connection or "—")
            connection.set_xalign(0)
            connection.set_hexpand(True)
            connection.add_css_class("swir-muted")
            box.append(connection)
            row.set_child(box)
            self.listbox.append(row)

    def _on_mapped(self, _window: Gtk.Window) -> None:
        if not self.e2e or not self.evidence_path:
            return
        path = pathlib.Path(self.evidence_path)
        runtime_text = os.environ.get("XDG_RUNTIME_DIR", "")
        if not runtime_text or path.parent.resolve() != pathlib.Path(runtime_text).resolve():
            raise RuntimeError("refusing SWIR Network Center evidence path outside XDG_RUNTIME_DIR")
        localized_surface_verified = bool(
            self.window
            and self.window.get_title() == self._t("window_title")
            and self.refresh_button
            and self.refresh_button.get_label() == self._t("refresh")
            and self.footer_label
            and self.footer_label.get_text() == self._t("footer")
        )
        payload = {
            "schema": EVIDENCE_SCHEMA,
            "passed": self.last_nmcli_present and localized_surface_verified,
            "applicationId": APP_ID,
            "nativeToolkit": "gtk4",
            "displayProtocol": "wayland",
            "windowMapped": True,
            "privilegedOperations": False,
            "mutationControlsExposed": False,
            "nmcliAbsolutePath": str(NMCLI),
            "nmcliPresent": self.last_nmcli_present,
            "networkManagerReachable": self.last_manager_reachable,
            "deviceQuerySucceeded": self.last_device_query_succeeded,
            "visibleDeviceCount": self.last_device_count,
            "deviceRowsBounded": MAX_DEVICE_ROWS,
            "queryTimeoutSeconds": QUERY_TIMEOUT_SECONDS,
            "requestedLanguage": self.locale.requested_language,
            "catalogLanguage": self.locale.catalog_language,
            "translationFallback": self.locale.fallback,
            "textDirection": self.locale.text_direction,
            "localizedWindowTitle": self._t("window_title"),
            "localizedRefreshLabel": self._t("refresh"),
            "localizedSurfaceVerified": localized_surface_verified,
            "refreshButtonFocusable": bool(self.refresh_button and self.refresh_button.get_focusable()),
            "localizedTooltips": bool(
                self.refresh_button
                and self.refresh_button.get_tooltip_text() == self._t("refresh_tooltip")
                and self.listbox
                and self.listbox.get_tooltip_text() == self._t("devices_tooltip")
            ),
        }
        path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
        path.chmod(0o600)
        GLib.timeout_add(250, self._finish_e2e)

    def _finish_e2e(self) -> bool:
        self.quit()
        return False


if __name__ == "__main__":
    raise SystemExit(SwirNetworkCenter().run(sys.argv))
