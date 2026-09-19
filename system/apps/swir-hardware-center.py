#!/usr/bin/env python3
"""SWIR Hardware & Driver Center — native read-only hardware diagnostics UI."""

from __future__ import annotations

import json
import os
import pathlib
import sys
import threading
from typing import Final

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gdk, GLib, Gtk  # noqa: E402

LIBDIR = pathlib.Path("/usr/local/lib/swir")
if LIBDIR.is_dir() and str(LIBDIR) not in sys.path:
    sys.path.insert(0, str(LIBDIR))

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
EVIDENCE_SCHEMA: Final = "swir.native-hardware-center-runtime-evidence/0.1"

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


class SwirHardwareCenter(Gtk.Application):
    def __init__(self) -> None:
        super().__init__(application_id=APP_ID)
        self.window: Gtk.ApplicationWindow | None = None
        self.summary_label: Gtk.Label | None = None
        self.devices_list: Gtk.ListBox | None = None
        self.operations_list: Gtk.ListBox | None = None
        self.firmware_list: Gtk.ListBox | None = None
        self.refresh_button: Gtk.Button | None = None
        self.e2e = os.environ.get("SWIR_APP_E2E", "0") == "1"
        self.evidence_path = os.environ.get("SWIR_APP_EVIDENCE_PATH", "")
        self.window_mapped = False
        self.refresh_complete = False
        self.evidence_written = False
        self.last_report: HardwareReport | None = None
        self.last_error = ""

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
        window.set_title("SWIR Hardware & Driver Center")
        window.set_default_size(1080, 720)
        window.add_css_class("swir-app")
        self.window = window

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        window.set_child(root)

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        header.add_css_class("swir-header")
        brand = Gtk.Label(label="◆  SWIR Hardware & Driver Center")
        brand.add_css_class("swir-brand")
        brand.set_xalign(0)
        header.append(brand)
        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        header.append(spacer)
        self.refresh_button = Gtk.Button(label="Refresh diagnostics")
        self.refresh_button.add_css_class("swir-button")
        self.refresh_button.connect("clicked", self._refresh_clicked)
        header.append(self.refresh_button)
        root.append(header)

        self.summary_label = Gtk.Label(label="Reading trusted hardware diagnostics…", wrap=True)
        self.summary_label.set_xalign(0)
        self.summary_label.set_selectable(True)
        self.summary_label.add_css_class("swir-card")
        root.append(self.summary_label)

        stack = Gtk.Stack()
        stack.set_hexpand(True)
        stack.set_vexpand(True)
        switcher = Gtk.StackSwitcher(stack=stack)
        switcher.set_halign(Gtk.Align.CENTER)
        root.append(switcher)

        self.devices_list = Gtk.ListBox()
        self.devices_list.set_selection_mode(Gtk.SelectionMode.NONE)
        devices_scroll = Gtk.ScrolledWindow()
        devices_scroll.set_child(self.devices_list)
        stack.add_titled(devices_scroll, "devices", "Devices")

        self.operations_list = Gtk.ListBox()
        self.operations_list.set_selection_mode(Gtk.SelectionMode.NONE)
        operations_scroll = Gtk.ScrolledWindow()
        operations_scroll.set_child(self.operations_list)
        stack.add_titled(operations_scroll, "reviews", "Recommended reviews")

        self.firmware_list = Gtk.ListBox()
        self.firmware_list.set_selection_mode(Gtk.SelectionMode.NONE)
        firmware_scroll = Gtk.ScrolledWindow()
        firmware_scroll.set_child(self.firmware_list)
        stack.add_titled(firmware_scroll, "firmware", "Firmware updates")

        footer = Gtk.Label(
            label=(
                "Read-only diagnostics • Linux in-tree drivers and linux-firmware first • "
                "LVFS candidates are review-only here • no random binary downloads • no Windows kernel-driver fallback"
            ),
            wrap=True,
        )
        footer.add_css_class("swir-muted")
        footer.set_xalign(0)
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
            self.summary_label.set_text("Reading trusted hardware diagnostics…")
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
            GLib.idle_add(self._apply_error, f"Unexpected diagnostics failure: {exc}"[:500])
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
        self.summary_label.set_text(f"Hardware diagnostics unavailable: {message}")
        self.summary_label.add_css_class("swir-warning")
        self._clear_list(self.devices_list)
        self._clear_list(self.operations_list)
        self._clear_list(self.firmware_list)
        self._append_message(self.devices_list, "No trusted hardware report is available.")
        self._append_message(self.operations_list, "No driver or firmware review is available.")
        self._append_message(self.firmware_list, "No trusted LVFS firmware inventory is available.")
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
            f"{report.distribution} • kernel {report.kernel} • "
            f"{report.devices_total} devices • {report.healthy} healthy • "
            f"{report.attention} attention • {report.unknown} unknown • "
            f"fwupd {'available' if report.fwupd_available else 'unavailable'} • "
            f"LVFS inventory {'ready' if report.firmware_inventory_ready else 'not ready'} • "
            f"{len(report.firmware_updates)} trusted firmware update(s)"
        )
        self._clear_list(self.devices_list)
        self._clear_list(self.operations_list)
        self._clear_list(self.firmware_list)

        if not report.devices:
            self._append_message(self.devices_list, "No PCI/USB devices were visible to this session.")
        for device in report.devices:
            row = Gtk.ListBoxRow()
            row.add_css_class("swir-row")
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
            title = Gtk.Label(
                label=f"{device.key}  •  {device.status}  •  driver {device.driver_status}: {device.module}",
                wrap=True,
            )
            title.set_xalign(0)
            box.append(title)
            detail = Gtk.Label(
                label=f"{device.bus.upper()}  {device.ids or 'IDs unavailable'}  • catalog: {device.catalog_entries}",
                wrap=True,
            )
            detail.set_xalign(0)
            detail.add_css_class("swir-muted")
            box.append(detail)
            row.set_child(box)
            self.devices_list.append(row)

        if not report.operations:
            self._append_message(self.operations_list, "No reviewed driver/firmware operations are currently proposed.")
        for operation in report.operations:
            row = Gtk.ListBoxRow()
            row.add_css_class("swir-row")
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
            title = Gtk.Label(
                label=(
                    f"{operation.kind} • {operation.device_key} • "
                    f"{'privileged review' if operation.privilege_required else 'diagnostic'}"
                ),
                wrap=True,
            )
            title.set_xalign(0)
            box.append(title)
            detail = Gtk.Label(
                label=f"{operation.reason or 'Review required'}  • sources: {operation.source_classes}",
                wrap=True,
            )
            detail.set_xalign(0)
            detail.add_css_class("swir-muted")
            box.append(detail)
            row.set_child(box)
            self.operations_list.append(row)

        if not report.firmware_inventory_ready:
            message = "Trusted LVFS firmware inventory is not ready."
            if report.firmware_error_code:
                message += f" Diagnostic code: {report.firmware_error_code}."
            self._append_message(self.firmware_list, message)
        elif not report.firmware_updates:
            self._append_message(self.firmware_list, "No trusted LVFS firmware updates are currently offered.")
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
                label=(
                    f"LVFS • release {update.release_id} • {update.checksum_count} signed metadata checksum(s) • "
                    f"{'reboot/power-cycle review required' if update.requires_reboot else 'post-update verification required'}"
                ),
                wrap=True,
            )
            detail.set_xalign(0)
            detail.add_css_class("swir-muted")
            box.append(detail)
            source = Gtk.Label(label=f"Read-only source binding: {update.source_ref}", wrap=True, selectable=True)
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
        payload = {
            "schema": EVIDENCE_SCHEMA,
            "passed": report is not None and not self.last_error,
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
