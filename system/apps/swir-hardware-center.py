#!/usr/bin/env python3
"""SWIR Hardware & Driver Center — native read-only hardware diagnostics UI."""

from __future__ import annotations

import json
import os
import pathlib
import sys
import threading
from dataclasses import dataclass
from typing import Final, Mapping

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gdk, GLib, Gtk  # noqa: E402

LIBDIR = pathlib.Path("/usr/local/lib/swir")
if LIBDIR.is_dir() and str(LIBDIR) not in sys.path:
    sys.path.insert(0, str(LIBDIR))

from core_runtime import UserSettingsStore, normalize_language_tag  # noqa: E402
from hardware_center_runtime import (  # noqa: E402
    HardwareCenterError,
    HardwareReport,
    MAX_DEVICE_ROWS,
    MAX_FIRMWARE_ROWS,
    MAX_OPERATION_ROWS,
    QUERY_TIMEOUT_SECONDS,
    read_hardware_report,
)

APP_ID: Final = "dev.swir.HardwareCenter"
EVIDENCE_SCHEMA: Final = "swir.native-hardware-center-runtime-evidence/0.2"

CSS = b"""
window.swir-app { background: #02050A; color: #F4FAFF; }
.swir-header { background: #07111C; border-bottom: 1px solid #0088FF; padding: 10px 14px; }
.swir-brand { color: #62E5FF; font-size: 18px; font-weight: 800; }
.swir-muted { color: #8DA8B8; }
.swir-card { background: #07111C; border: 1px solid rgba(98,229,255,0.28); border-radius: 12px; padding: 10px 14px; }
.swir-row { padding: 8px 10px; border-bottom: 1px solid rgba(98,229,255,0.08); }
.swir-button { background: #07111C; color: #F4FAFF; border: 1px solid #0088FF; border-radius: 10px; padding: 7px 12px; }
.swir-button:hover { border-color: #62E5FF; }
.swir-warning { color: #FFD27A; }
"""

_TRANSLATIONS: Final[Mapping[str, Mapping[str, str]]] = {
    "en": {
        "window_title": "SWIR Hardware & Driver Center",
        "brand": "◆  SWIR Hardware & Driver Center",
        "refresh": "Refresh diagnostics",
        "refresh_tooltip": "Refresh trusted read-only hardware diagnostics",
        "tabs_tooltip": "Hardware, driver review and trusted firmware inventory",
        "reading": "Reading trusted hardware diagnostics…",
        "devices": "Devices",
        "reviews": "Recommended reviews",
        "firmware": "Firmware updates",
        "footer": (
            "Read-only diagnostics • Linux in-tree drivers and linux-firmware first • "
            "LVFS candidates are review-only here • no random binary downloads • no Windows kernel-driver fallback"
        ),
        "unexpected_failure": "Unexpected diagnostics failure: {reason}",
        "unavailable": "Hardware diagnostics unavailable: {reason}",
        "no_report": "No trusted hardware report is available.",
        "no_review": "No driver or firmware review is available.",
        "no_inventory": "No trusted LVFS firmware inventory is available.",
        "summary": (
            "{distribution} • kernel {kernel} • {devices} devices • {healthy} healthy • "
            "{attention} attention • {unknown} unknown • fwupd {fwupd} • "
            "LVFS inventory {inventory} • {updates} trusted firmware update(s)"
        ),
        "available": "available",
        "not_available": "unavailable",
        "ready": "ready",
        "not_ready": "not ready",
        "no_devices": "No PCI/USB devices were visible to this session.",
        "device_title": "{key}  •  {status}  •  driver {driver_status}: {module}",
        "device_detail": "{bus}  {ids}  • catalog: {catalog}",
        "ids_unavailable": "IDs unavailable",
        "no_operations": "No reviewed driver/firmware operations are currently proposed.",
        "operation_title": "{kind} • {device} • {privilege}",
        "privileged_review": "privileged review",
        "diagnostic": "diagnostic",
        "operation_detail": "{reason}  • sources: {sources}",
        "review_required": "Review required",
        "inventory_not_ready": "Trusted LVFS firmware inventory is not ready.",
        "diagnostic_code": " Diagnostic code: {code}.",
        "no_firmware_updates": "No trusted LVFS firmware updates are currently offered.",
        "firmware_detail": (
            "LVFS • release {release} • {checksums} signed metadata checksum(s) • {verification}"
        ),
        "reboot_review": "reboot/power-cycle review required",
        "post_update_review": "post-update verification required",
        "source_binding": "Read-only source binding: {source}",
    },
    "pl-PL": {
        "window_title": "Centrum sprzętu i sterowników SWIR",
        "brand": "◆  Centrum sprzętu i sterowników SWIR",
        "refresh": "Odśwież diagnostykę",
        "refresh_tooltip": "Odśwież zaufaną diagnostykę sprzętu tylko do odczytu",
        "tabs_tooltip": "Sprzęt, przegląd sterowników i zaufany spis firmware",
        "reading": "Odczytywanie zaufanej diagnostyki sprzętu…",
        "devices": "Urządzenia",
        "reviews": "Zalecane przeglądy",
        "firmware": "Aktualizacje firmware",
        "footer": (
            "Diagnostyka tylko do odczytu • najpierw sterowniki jądra Linux i linux-firmware • "
            "kandydaci LVFS są tutaj tylko do przeglądu • bez losowych plików binarnych • bez sterowników jądra Windows"
        ),
        "unexpected_failure": "Nieoczekiwany błąd diagnostyki: {reason}",
        "unavailable": "Diagnostyka sprzętu jest niedostępna: {reason}",
        "no_report": "Brak zaufanego raportu sprzętowego.",
        "no_review": "Brak przeglądu sterowników lub firmware.",
        "no_inventory": "Brak zaufanego spisu firmware LVFS.",
        "summary": (
            "{distribution} • jądro {kernel} • urządzenia: {devices} • sprawne: {healthy} • "
            "uwaga: {attention} • nieznane: {unknown} • fwupd: {fwupd} • "
            "spis LVFS: {inventory} • zaufane aktualizacje firmware: {updates}"
        ),
        "available": "dostępne",
        "not_available": "niedostępne",
        "ready": "gotowy",
        "not_ready": "niegotowy",
        "no_devices": "W tej sesji nie wykryto urządzeń PCI/USB.",
        "device_title": "{key}  •  {status}  •  sterownik {driver_status}: {module}",
        "device_detail": "{bus}  {ids}  • katalog: {catalog}",
        "ids_unavailable": "brak identyfikatorów",
        "no_operations": "Obecnie nie zaproponowano zweryfikowanych operacji sterownika/firmware.",
        "operation_title": "{kind} • {device} • {privilege}",
        "privileged_review": "przegląd uprzywilejowany",
        "diagnostic": "diagnostyka",
        "operation_detail": "{reason}  • źródła: {sources}",
        "review_required": "Wymagany przegląd",
        "inventory_not_ready": "Zaufany spis firmware LVFS nie jest gotowy.",
        "diagnostic_code": " Kod diagnostyczny: {code}.",
        "no_firmware_updates": "Obecnie brak zaufanych aktualizacji firmware LVFS.",
        "firmware_detail": (
            "LVFS • wydanie {release} • sumy kontrolne podpisanych metadanych: {checksums} • {verification}"
        ),
        "reboot_review": "wymagany przegląd restartu/cyklu zasilania",
        "post_update_review": "wymagana weryfikacja po aktualizacji",
        "source_binding": "Powiązanie źródła tylko do odczytu: {source}",
    },
    "nb-NO": {
        "window_title": "SWIR Maskinvare- og driversenter",
        "brand": "◆  SWIR Maskinvare- og driversenter",
        "refresh": "Oppdater diagnostikk",
        "refresh_tooltip": "Oppdater klarert skrivebeskyttet maskinvarediagnostikk",
        "tabs_tooltip": "Maskinvare, drivergjennomgang og klarert fastvareoversikt",
        "reading": "Leser klarert maskinvarediagnostikk…",
        "devices": "Enheter",
        "reviews": "Anbefalte gjennomganger",
        "firmware": "Fastvareoppdateringer",
        "footer": (
            "Skrivebeskyttet diagnostikk • Linux-drivere i kjernen og linux-firmware først • "
            "LVFS-kandidater er kun til gjennomgang her • ingen tilfeldige binærfiler • ingen Windows-kjernedriver som reserve"
        ),
        "unexpected_failure": "Uventet diagnostikkfeil: {reason}",
        "unavailable": "Maskinvarediagnostikk er utilgjengelig: {reason}",
        "no_report": "Ingen klarert maskinvarerapport er tilgjengelig.",
        "no_review": "Ingen driver- eller fastvaregjennomgang er tilgjengelig.",
        "no_inventory": "Ingen klarert LVFS-fastvareoversikt er tilgjengelig.",
        "summary": (
            "{distribution} • kjerne {kernel} • {devices} enheter • {healthy} friske • "
            "{attention} krever oppmerksomhet • {unknown} ukjente • fwupd {fwupd} • "
            "LVFS-oversikt {inventory} • {updates} klarerte fastvareoppdatering(er)"
        ),
        "available": "tilgjengelig",
        "not_available": "utilgjengelig",
        "ready": "klar",
        "not_ready": "ikke klar",
        "no_devices": "Ingen PCI/USB-enheter var synlige for denne økten.",
        "device_title": "{key}  •  {status}  •  driver {driver_status}: {module}",
        "device_detail": "{bus}  {ids}  • katalog: {catalog}",
        "ids_unavailable": "ID-er utilgjengelige",
        "no_operations": "Ingen gjennomgåtte driver-/fastvareoperasjoner er foreslått nå.",
        "operation_title": "{kind} • {device} • {privilege}",
        "privileged_review": "privilegert gjennomgang",
        "diagnostic": "diagnostikk",
        "operation_detail": "{reason}  • kilder: {sources}",
        "review_required": "Gjennomgang kreves",
        "inventory_not_ready": "Klarert LVFS-fastvareoversikt er ikke klar.",
        "diagnostic_code": " Diagnosekode: {code}.",
        "no_firmware_updates": "Ingen klarerte LVFS-fastvareoppdateringer tilbys nå.",
        "firmware_detail": (
            "LVFS • utgivelse {release} • {checksums} kontrollsum(er) for signerte metadata • {verification}"
        ),
        "reboot_review": "gjennomgang av omstart/strømsyklus kreves",
        "post_update_review": "verifisering etter oppdatering kreves",
        "source_binding": "Skrivebeskyttet kildebinding: {source}",
    },
}


@dataclass(frozen=True)
class HardwareLocale:
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


def hardware_locale(language: object) -> HardwareLocale:
    requested = normalize_language_tag(language) or "en"
    catalog = requested if requested in _TRANSLATIONS else "en"
    return HardwareLocale(requested, catalog, _TRANSLATIONS[catalog])


class SwirHardwareCenter(Gtk.Application):
    def __init__(self) -> None:
        super().__init__(application_id=APP_ID)
        self.window: Gtk.ApplicationWindow | None = None
        self.summary_label: Gtk.Label | None = None
        self.devices_list: Gtk.ListBox | None = None
        self.operations_list: Gtk.ListBox | None = None
        self.firmware_list: Gtk.ListBox | None = None
        self.refresh_button: Gtk.Button | None = None
        self.stack: Gtk.Stack | None = None
        self.footer_label: Gtk.Label | None = None
        self.settings_store = UserSettingsStore()
        self.locale = self._load_locale()
        self.e2e = os.environ.get("SWIR_APP_E2E", "0") == "1"
        self.evidence_path = os.environ.get("SWIR_APP_EVIDENCE_PATH", "")
        self.window_mapped = False
        self.refresh_complete = False
        self.evidence_written = False
        self.last_report: HardwareReport | None = None
        self.last_error = ""

    def _load_locale(self) -> HardwareLocale:
        try:
            language = self.settings_store.load().get("language", "en")
        except (OSError, RuntimeError, UnicodeError, ValueError):
            language = "en"
        return hardware_locale(language)

    def _t(self, key: str, **values: object) -> str:
        return self.locale.text(key, **values)

    def do_startup(self) -> None:
        Gtk.Application.do_startup(self)
        provider = Gtk.CssProvider()
        provider.load_from_data(CSS)
        display = Gdk.Display.get_default()
        if display is None:
            raise RuntimeError("SWIR Hardware Center requires a graphical display")
        Gtk.StyleContext.add_provider_for_display(display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    def do_activate(self) -> None:
        if self.window is not None:
            self.window.present()
            return

        window = Gtk.ApplicationWindow(application=self)
        window.set_title(self._t("window_title"))
        window.set_default_size(1080, 720)
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
        self.refresh_button = Gtk.Button(label=self._t("refresh"))
        self.refresh_button.add_css_class("swir-button")
        self.refresh_button.set_focusable(True)
        self.refresh_button.set_tooltip_text(self._t("refresh_tooltip"))
        self.refresh_button.connect("clicked", self._refresh_clicked)
        header.append(self.refresh_button)
        root.append(header)

        self.summary_label = Gtk.Label(label=self._t("reading"), wrap=True)
        self.summary_label.set_xalign(0)
        self.summary_label.set_selectable(True)
        self.summary_label.add_css_class("swir-card")
        root.append(self.summary_label)

        stack = Gtk.Stack()
        stack.set_hexpand(True)
        stack.set_vexpand(True)
        stack.set_tooltip_text(self._t("tabs_tooltip"))
        self.stack = stack
        switcher = Gtk.StackSwitcher(stack=stack)
        switcher.set_halign(Gtk.Align.CENTER)
        root.append(switcher)

        self.devices_list = Gtk.ListBox()
        self.devices_list.set_selection_mode(Gtk.SelectionMode.NONE)
        devices_scroll = Gtk.ScrolledWindow()
        devices_scroll.set_child(self.devices_list)
        stack.add_titled(devices_scroll, "devices", self._t("devices"))

        self.operations_list = Gtk.ListBox()
        self.operations_list.set_selection_mode(Gtk.SelectionMode.NONE)
        operations_scroll = Gtk.ScrolledWindow()
        operations_scroll.set_child(self.operations_list)
        stack.add_titled(operations_scroll, "reviews", self._t("reviews"))

        self.firmware_list = Gtk.ListBox()
        self.firmware_list.set_selection_mode(Gtk.SelectionMode.NONE)
        firmware_scroll = Gtk.ScrolledWindow()
        firmware_scroll.set_child(self.firmware_list)
        stack.add_titled(firmware_scroll, "firmware", self._t("firmware"))

        footer = Gtk.Label(label=self._t("footer"), wrap=True)
        footer.add_css_class("swir-muted")
        footer.set_xalign(0)
        self.footer_label = footer
        root.append(footer)

        window.connect("map", self._on_mapped)
        window.present()
        self._start_refresh()

    def _refresh_clicked(self, _button: Gtk.Button) -> None:
        self._start_refresh()

    def _start_refresh(self) -> None:
        if self.refresh_button is not None:
            self.refresh_button.set_sensitive(False)
        if self.summary_label is not None:
            self.summary_label.set_text(self._t("reading"))
        self.refresh_complete = False
        self.last_report = None
        self.last_error = ""
        thread = threading.Thread(target=self._refresh_worker, name="swir-hardware-report", daemon=True)
        thread.start()

    def _refresh_worker(self) -> None:
        try:
            report = read_hardware_report()
        except HardwareCenterError as exc:
            GLib.idle_add(self._apply_error, str(exc)[:500])
        except Exception as exc:
            GLib.idle_add(self._apply_error, self._t("unexpected_failure", reason=str(exc)[:420]))
        else:
            GLib.idle_add(self._apply_report, report)

    @staticmethod
    def _clear_list(listbox: Gtk.ListBox) -> None:
        child = listbox.get_first_child()
        while child is not None:
            next_child = child.get_next_sibling()
            listbox.remove(child)
            child = next_child

    def _append_message(self, listbox: Gtk.ListBox, text: str) -> None:
        row = Gtk.ListBoxRow()
        label = Gtk.Label(label=text, wrap=True)
        label.set_xalign(0)
        label.add_css_class("swir-muted")
        row.set_child(label)
        listbox.append(row)

    def _apply_error(self, message: str) -> bool:
        assert (
            self.summary_label is not None
            and self.devices_list is not None
            and self.operations_list is not None
            and self.firmware_list is not None
        )
        self.last_error = message
        self.summary_label.set_text(self._t("unavailable", reason=message))
        self.summary_label.add_css_class("swir-warning")
        self._clear_list(self.devices_list)
        self._clear_list(self.operations_list)
        self._clear_list(self.firmware_list)
        self._append_message(self.devices_list, self._t("no_report"))
        self._append_message(self.operations_list, self._t("no_review"))
        self._append_message(self.firmware_list, self._t("no_inventory"))
        self._finish_refresh()
        return False

    def _apply_report(self, report: HardwareReport) -> bool:
        assert (
            self.summary_label is not None
            and self.devices_list is not None
            and self.operations_list is not None
            and self.firmware_list is not None
        )
        self.last_report = report
        self.summary_label.remove_css_class("swir-warning")
        self.summary_label.set_text(
            self._t(
                "summary",
                distribution=report.distribution,
                kernel=report.kernel,
                devices=report.devices_total,
                healthy=report.healthy,
                attention=report.attention,
                unknown=report.unknown,
                fwupd=self._t("available") if report.fwupd_available else self._t("not_available"),
                inventory=self._t("ready") if report.firmware_inventory_ready else self._t("not_ready"),
                updates=len(report.firmware_updates),
            )
        )
        self._clear_list(self.devices_list)
        self._clear_list(self.operations_list)
        self._clear_list(self.firmware_list)

        if not report.devices:
            self._append_message(self.devices_list, self._t("no_devices"))
        for device in report.devices:
            row = Gtk.ListBoxRow()
            row.add_css_class("swir-row")
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
            title = Gtk.Label(
                label=self._t(
                    "device_title",
                    key=device.key,
                    status=device.status,
                    driver_status=device.driver_status,
                    module=device.module,
                ),
                wrap=True,
            )
            title.set_xalign(0)
            box.append(title)
            detail = Gtk.Label(
                label=self._t(
                    "device_detail",
                    bus=device.bus.upper(),
                    ids=device.ids or self._t("ids_unavailable"),
                    catalog=device.catalog_entries,
                ),
                wrap=True,
            )
            detail.set_xalign(0)
            detail.add_css_class("swir-muted")
            box.append(detail)
            row.set_child(box)
            self.devices_list.append(row)

        if not report.operations:
            self._append_message(self.operations_list, self._t("no_operations"))
        for operation in report.operations:
            row = Gtk.ListBoxRow()
            row.add_css_class("swir-row")
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
            title = Gtk.Label(
                label=self._t(
                    "operation_title",
                    kind=operation.kind,
                    device=operation.device_key,
                    privilege=self._t("privileged_review") if operation.privilege_required else self._t("diagnostic"),
                ),
                wrap=True,
            )
            title.set_xalign(0)
            box.append(title)
            detail = Gtk.Label(
                label=self._t(
                    "operation_detail",
                    reason=operation.reason or self._t("review_required"),
                    sources=operation.source_classes,
                ),
                wrap=True,
            )
            detail.set_xalign(0)
            detail.add_css_class("swir-muted")
            box.append(detail)
            row.set_child(box)
            self.operations_list.append(row)

        if not report.firmware_inventory_ready:
            message = self._t("inventory_not_ready")
            if report.firmware_error_code:
                message += self._t("diagnostic_code", code=report.firmware_error_code)
            self._append_message(self.firmware_list, message)
        elif not report.firmware_updates:
            self._append_message(self.firmware_list, self._t("no_firmware_updates"))
        for update in report.firmware_updates:
            row = Gtk.ListBoxRow()
            row.add_css_class("swir-row")
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
            title = Gtk.Label(
                label=f"{update.device_name} • {update.current_version} → {update.target_version}",
                wrap=True,
            )
            title.set_xalign(0)
            box.append(title)
            detail = Gtk.Label(
                label=self._t(
                    "firmware_detail",
                    release=update.release_id,
                    checksums=update.checksum_count,
                    verification=(
                        self._t("reboot_review") if update.requires_reboot else self._t("post_update_review")
                    ),
                ),
                wrap=True,
            )
            detail.set_xalign(0)
            detail.add_css_class("swir-muted")
            box.append(detail)
            source = Gtk.Label(
                label=self._t("source_binding", source=update.source_ref),
                wrap=True,
                selectable=True,
            )
            source.set_xalign(0)
            source.add_css_class("swir-muted")
            box.append(source)
            row.set_child(box)
            self.firmware_list.append(row)

        self._finish_refresh()
        return False

    def _finish_refresh(self) -> None:
        self.refresh_complete = True
        if self.refresh_button is not None:
            self.refresh_button.set_sensitive(True)
        self._maybe_write_evidence()

    def _on_mapped(self, _window: Gtk.Window) -> None:
        self.window_mapped = True
        self._maybe_write_evidence()

    def _maybe_write_evidence(self) -> None:
        if (
            not self.e2e
            or not self.evidence_path
            or self.evidence_written
            or not self.window_mapped
            or not self.refresh_complete
        ):
            return
        path = pathlib.Path(self.evidence_path)
        runtime_text = os.environ.get("XDG_RUNTIME_DIR", "")
        if not runtime_text or path.parent.resolve() != pathlib.Path(runtime_text).resolve():
            raise RuntimeError("refusing SWIR Hardware Center evidence path outside XDG_RUNTIME_DIR")
        report = self.last_report
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
            "passed": report is not None and not self.last_error and localized_surface_verified,
            "applicationId": APP_ID,
            "nativeToolkit": "gtk4",
            "displayProtocol": "wayland",
            "windowMapped": True,
            "privilegedOperationsInUi": False,
            "mutationControlsExposed": False,
            "firmwareMutationControlsExposed": False,
            "driverReportReadOnly": True,
            "firmwareInventoryReadOnly": True,
            "arbitraryDriverDownloadsAllowed": False,
            "windowsKernelDriversAsLinuxPath": False,
            "queryTimeoutSeconds": QUERY_TIMEOUT_SECONDS,
            "deviceRowsBounded": MAX_DEVICE_ROWS,
            "operationRowsBounded": MAX_OPERATION_ROWS,
            "firmwareRowsBounded": MAX_FIRMWARE_ROWS,
            "reportLoaded": report is not None,
            "visibleDeviceCount": len(report.devices) if report else 0,
            "visibleOperationCount": len(report.operations) if report else 0,
            "visibleFirmwareUpdateCount": len(report.firmware_updates) if report else 0,
            "fwupdAvailable": report.fwupd_available if report else False,
            "lvfsMetadataPresent": report.lvfs_metadata_present if report else False,
            "firmwareInventoryReady": report.firmware_inventory_ready if report else False,
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
                and self.stack
                and self.stack.get_tooltip_text() == self._t("tabs_tooltip")
            ),
            "error": self.last_error,
        }
        path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
        path.chmod(0o600)
        self.evidence_written = True
        GLib.timeout_add(250, self._finish_e2e)

    def _finish_e2e(self) -> bool:
        self.quit()
        return False


if __name__ == "__main__":
    raise SystemExit(SwirHardwareCenter().run(sys.argv))
