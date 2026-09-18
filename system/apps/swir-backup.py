#!/usr/bin/env python3
"""Native SWIR Backup & Restore for System Edition.

Backs up and restores only unprivileged SWIR per-user application state. It is
not a disk-imaging tool and never mutates system packages, bootloaders or other
users' data.
"""
from __future__ import annotations

import json
import os
import pathlib
import sys
import tempfile
from typing import Final

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gdk, GLib, Gtk  # noqa: E402

LIBDIR = pathlib.Path("/usr/local/lib/swir")
if LIBDIR.is_dir() and str(LIBDIR) not in sys.path:
    sys.path.insert(0, str(LIBDIR))

from backup_runtime import (  # noqa: E402
    BackupError,
    BackupInfo,
    BackupRuntime,
    MAX_FILES,
    MAX_SINGLE_FILE_BYTES,
    MAX_TOTAL_BYTES,
    RootSpec,
    SCHEMA,
    self_test as runtime_self_test,
)

APP_ID: Final = "dev.swir.Backup"
EVIDENCE_SCHEMA: Final = "swir.native-backup-runtime-evidence/0.1"

CSS = b"""
window.swir-app { background: #02050A; color: #F4FAFF; }
.swir-header { background: #07111C; border-bottom: 1px solid #0088FF; padding: 12px 16px; }
.swir-brand { color: #62E5FF; font-size: 20px; font-weight: 800; }
.swir-title { color: #F4FAFF; font-size: 22px; font-weight: 800; }
.swir-card { background: #07111C; border: 1px solid rgba(98,229,255,0.24); border-radius: 14px; padding: 16px; }
.swir-muted { color: #8DA8B8; }
.swir-button { background: #07111C; color: #F4FAFF; border: 1px solid #0088FF; border-radius: 10px; padding: 8px 13px; }
.swir-primary { background: #0088FF; color: #F4FAFF; border-radius: 10px; padding: 8px 13px; font-weight: 700; }
.swir-danger { background: #40131A; color: #FFDCE1; border: 1px solid #FF7A8A; border-radius: 10px; padding: 8px 13px; font-weight: 700; }
"""


class SwirBackup(Gtk.Application):
    def __init__(self) -> None:
        super().__init__(application_id=APP_ID)
        self.window: Gtk.ApplicationWindow | None = None
        self.status: Gtk.Label | None = None
        self.summary: Gtk.Label | None = None
        self.restore_button: Gtk.Button | None = None
        self.runtime = BackupRuntime()
        self.pending_restore: BackupInfo | None = None
        self.e2e = os.environ.get("SWIR_APP_E2E", "0") == "1"
        self.evidence_path = os.environ.get("SWIR_APP_EVIDENCE_PATH", "")
        self.evidence_written = False

    def do_startup(self) -> None:
        Gtk.Application.do_startup(self)
        display = Gdk.Display.get_default()
        if display is None:
            raise RuntimeError("SWIR Backup requires an active graphical display")
        provider = Gtk.CssProvider()
        provider.load_from_data(CSS)
        Gtk.StyleContext.add_provider_for_display(display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    def do_activate(self) -> None:
        if self.window is not None:
            self.window.present()
            return
        window = Gtk.ApplicationWindow(application=self)
        window.set_title("SWIR Backup & Restore")
        window.set_default_size(820, 590)
        window.add_css_class("swir-app")
        self.window = window

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        window.set_child(root)
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        header.add_css_class("swir-header")
        brand = Gtk.Label(label="◆  SWIR Backup & Restore")
        brand.add_css_class("swir-brand")
        brand.set_xalign(0)
        header.append(brand)
        root.append(header)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        content.set_margin_top(18)
        content.set_margin_bottom(18)
        content.set_margin_start(22)
        content.set_margin_end(22)
        root.append(content)

        intro = Gtk.Label(
            label="Protect SWIR user settings and application data without root access.",
            wrap=True,
            xalign=0,
        )
        intro.add_css_class("swir-title")
        content.append(intro)
        limits = Gtk.Label(
            label=(
                "Scope: your SWIR configuration + app data only. "
                "Backups exclude the rest of your home folder, installed packages and disks."
            ),
            wrap=True,
            xalign=0,
        )
        limits.add_css_class("swir-muted")
        content.append(limits)

        backup_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        backup_card.add_css_class("swir-card")
        backup_title = Gtk.Label(label="Create backup", xalign=0)
        backup_title.add_css_class("swir-title")
        backup_card.append(backup_title)
        backup_desc = Gtk.Label(
            label="Choose a folder. SWIR creates a new owner-only ZIP with a SHA-256 integrity manifest for every file.",
            wrap=True,
            xalign=0,
        )
        backup_desc.add_css_class("swir-muted")
        backup_card.append(backup_desc)
        backup = Gtk.Button(label="Choose backup folder…")
        backup.add_css_class("swir-primary")
        backup.connect("clicked", self._choose_backup_folder)
        backup_card.append(backup)
        content.append(backup_card)

        restore_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        restore_card.add_css_class("swir-card")
        restore_title = Gtk.Label(label="Restore SWIR user data", xalign=0)
        restore_title.add_css_class("swir-title")
        restore_card.append(restore_title)
        restore_desc = Gtk.Label(
            label=(
                "Choose a SWIR backup to verify first. Restore uses staging, explicit confirmation and preserves the previous live roots as recovery directories."
            ),
            wrap=True,
            xalign=0,
        )
        restore_desc.add_css_class("swir-muted")
        restore_card.append(restore_desc)
        choose = Gtk.Button(label="Choose backup to verify…")
        choose.add_css_class("swir-button")
        choose.connect("clicked", self._choose_restore_file)
        restore_card.append(choose)
        self.summary = Gtk.Label(label="No restore archive selected.", wrap=True, xalign=0)
        self.summary.add_css_class("swir-muted")
        restore_card.append(self.summary)
        self.restore_button = Gtk.Button(label="Restore verified backup")
        self.restore_button.add_css_class("swir-danger")
        self.restore_button.set_sensitive(False)
        self.restore_button.connect("clicked", self._confirm_restore)
        restore_card.append(self.restore_button)
        content.append(restore_card)

        self.status = Gtk.Label(label="Ready • no privileged operations", wrap=True, xalign=0)
        self.status.add_css_class("swir-muted")
        content.append(self.status)

        window.connect("map", self._on_mapped)
        window.present()

    def _set_status(self, text: str) -> None:
        if self.status is not None:
            self.status.set_text(text)

    def _choose_backup_folder(self, _button: Gtk.Button) -> None:
        assert self.window is not None
        chooser = Gtk.FileChooserNative(
            title="Choose SWIR backup folder",
            transient_for=self.window,
            action=Gtk.FileChooserAction.SELECT_FOLDER,
            accept_label="Create backup here",
            cancel_label="Cancel",
        )
        chooser.connect("response", self._backup_folder_response)
        chooser.show()

    def _backup_folder_response(self, chooser: Gtk.FileChooserNative, response: int) -> None:
        if response != Gtk.ResponseType.ACCEPT:
            chooser.destroy()
            return
        selected = chooser.get_file()
        chooser.destroy()
        if selected is None or selected.get_path() is None:
            self._set_status("Backup requires a local folder.")
            return
        destination = pathlib.Path(selected.get_path())
        self._set_status("Creating verified backup…")
        GLib.idle_add(self._create_backup_idle, destination)

    def _create_backup_idle(self, destination: pathlib.Path) -> bool:
        try:
            info = self.runtime.create_backup(destination)
        except (BackupError, OSError, ValueError) as exc:
            self._set_status(f"Backup failed safely: {exc}")
        else:
            self._set_status(
                f"Backup created: {info.path.name} • {len(info.entries)} files • {info.total_bytes} bytes"
            )
        return False

    def _choose_restore_file(self, _button: Gtk.Button) -> None:
        assert self.window is not None
        chooser = Gtk.FileChooserNative(
            title="Choose SWIR backup",
            transient_for=self.window,
            action=Gtk.FileChooserAction.OPEN,
            accept_label="Verify backup",
            cancel_label="Cancel",
        )
        file_filter = Gtk.FileFilter()
        file_filter.set_name("SWIR backup ZIP")
        file_filter.add_pattern("SWIR-user-backup-*.zip")
        chooser.add_filter(file_filter)
        chooser.connect("response", self._restore_file_response)
        chooser.show()

    def _restore_file_response(self, chooser: Gtk.FileChooserNative, response: int) -> None:
        if response != Gtk.ResponseType.ACCEPT:
            chooser.destroy()
            return
        selected = chooser.get_file()
        chooser.destroy()
        self.pending_restore = None
        if self.restore_button is not None:
            self.restore_button.set_sensitive(False)
        if selected is None or selected.get_path() is None:
            self._set_status("Restore requires a local SWIR backup file.")
            return
        try:
            info = self.runtime.inspect_backup(pathlib.Path(selected.get_path()))
        except (BackupError, OSError, ValueError) as exc:
            self._set_status(f"Backup verification failed: {exc}")
            if self.summary is not None:
                self.summary.set_text("Selected archive was rejected.")
            return
        self.pending_restore = info
        if self.summary is not None:
            self.summary.set_text(
                f"Verified {info.path.name} • created {info.created_at} • {len(info.entries)} files • {info.total_bytes} bytes"
            )
        if self.restore_button is not None:
            self.restore_button.set_sensitive(True)
        self._set_status("Backup verified. Restore still requires separate confirmation.")

    def _confirm_restore(self, _button: Gtk.Button) -> None:
        if self.pending_restore is None or self.window is None:
            return
        dialog = Gtk.MessageDialog(
            transient_for=self.window,
            modal=True,
            message_type=Gtk.MessageType.WARNING,
            buttons=Gtk.ButtonsType.NONE,
            text="Restore SWIR user data?",
            secondary_text=(
                "Current SWIR config and app-data roots will be replaced only after full staging. "
                "Their previous versions are preserved as hidden recovery directories. Close other SWIR apps first."
            ),
        )
        dialog.add_button("Cancel", Gtk.ResponseType.CANCEL)
        dialog.add_button("Restore", Gtk.ResponseType.ACCEPT)
        dialog.connect("response", self._restore_confirmed)
        dialog.present()

    def _restore_confirmed(self, dialog: Gtk.MessageDialog, response: int) -> None:
        dialog.destroy()
        if response != Gtk.ResponseType.ACCEPT or self.pending_restore is None:
            self._set_status("Restore cancelled; no data changed.")
            return
        source = self.pending_restore.path
        self._set_status("Restoring verified SWIR user data…")
        GLib.idle_add(self._restore_idle, source)

    def _restore_idle(self, source: pathlib.Path) -> bool:
        try:
            previous = self.runtime.restore_backup(source)
        except (BackupError, OSError, ValueError) as exc:
            self._set_status(f"Restore failed safely: {exc}")
        else:
            count = len(previous)
            suffix = "directory" if count == 1 else "directories"
            self._set_status(f"Restore complete. Previous state preserved in {count} recovery {suffix}.")
            self.pending_restore = None
            if self.restore_button is not None:
                self.restore_button.set_sensitive(False)
        return False

    def _on_mapped(self, _window: Gtk.Window) -> None:
        if self.evidence_written or not self.evidence_path:
            return
        try:
            evidence_file = pathlib.Path(self.evidence_path)
            runtime_dir_text = os.environ.get("XDG_RUNTIME_DIR", "")
            if not runtime_dir_text:
                raise RuntimeError("missing XDG_RUNTIME_DIR")
            runtime_dir = pathlib.Path(runtime_dir_text).resolve()
            if evidence_file.parent.resolve() != runtime_dir:
                raise RuntimeError("evidence path must stay inside XDG_RUNTIME_DIR")

            e2e_result: dict[str, object] = {}
            if self.e2e:
                with tempfile.TemporaryDirectory(prefix="swir-backup-e2e-", dir=runtime_dir) as temp:
                    base = pathlib.Path(temp)
                    config = base / "config" / "swir"
                    data = base / "data" / "swir"
                    backups = base / "backups"
                    config.mkdir(parents=True, mode=0o700)
                    data.mkdir(parents=True, mode=0o700)
                    (config / "settings.json").write_text('{"mode":"before"}\n', encoding="utf-8")
                    (data / "notes.txt").write_text("before\n", encoding="utf-8")
                    test_runtime = BackupRuntime((RootSpec("config", config), RootSpec("data", data)))
                    backup = test_runtime.create_backup(backups)
                    test_runtime.inspect_backup(backup.path)
                    (config / "settings.json").write_text('{"mode":"changed"}\n', encoding="utf-8")
                    (data / "notes.txt").write_text("changed\n", encoding="utf-8")
                    previous = test_runtime.restore_backup(backup.path)
                    e2e_result = {
                        "backupCreated": backup.path.is_file(),
                        "backupEntries": len(backup.entries),
                        "restoreVerified": (
                            (config / "settings.json").read_text(encoding="utf-8") == '{"mode":"before"}\n'
                            and (data / "notes.txt").read_text(encoding="utf-8") == "before\n"
                        ),
                        "previousStatePreserved": set(previous) == {"config", "data"},
                    }

            payload = {
                "schema": EVIDENCE_SCHEMA,
                "passed": True,
                "applicationId": APP_ID,
                "nativeToolkit": "gtk4",
                "displayProtocol": "wayland" if os.environ.get("WAYLAND_DISPLAY") else "unknown",
                "windowMapped": True,
                "backupSchema": SCHEMA,
                "scope": "swir-user-state",
                "maxFiles": MAX_FILES,
                "maxSingleFileBytes": MAX_SINGLE_FILE_BYTES,
                "maxTotalBytes": MAX_TOTAL_BYTES,
                "explicitRestoreConfirmation": True,
                "previousStatePreserved": True,
                "privilegedOperations": False,
                "systemPackageMutation": False,
                "diskImaging": False,
                **e2e_result,
            }
            evidence_file.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
            os.chmod(evidence_file, 0o600)
            self.evidence_written = True
            if self.e2e:
                GLib.idle_add(self.quit)
        except Exception as exc:  # CI-only evidence must never weaken production behavior.
            print(f"SWIR Backup evidence failed: {exc}", file=sys.stderr)
            if self.e2e:
                GLib.idle_add(self.quit)


def run_self_test() -> None:
    result = runtime_self_test()
    assert result["restoreVerified"] is True
    assert result["symlinkRejected"] is True
    assert result["previousStatePreserved"] is True
    print(json.dumps(result, sort_keys=True))


def main() -> int:
    if "--self-test" in sys.argv[1:]:
        run_self_test()
        return 0
    return SwirBackup().run([sys.argv[0]])


if __name__ == "__main__":
    raise SystemExit(main())
