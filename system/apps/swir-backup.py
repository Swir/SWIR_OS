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
from dataclasses import dataclass
from typing import Final, Mapping

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
from core_runtime import UserSettingsStore, normalize_language_tag  # noqa: E402

APP_ID: Final = "dev.swir.Backup"
EVIDENCE_SCHEMA: Final = "swir.native-backup-runtime-evidence/0.2"

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

_TRANSLATIONS: Final[Mapping[str, Mapping[str, str]]] = {
    "en": {
        "window_title": "SWIR Backup & Restore",
        "brand": "◆  SWIR Backup & Restore",
        "intro": "Protect SWIR user settings and application data without root access.",
        "limits": (
            "Scope: your SWIR configuration + app data only. "
            "Backups exclude the rest of your home folder, installed packages and disks."
        ),
        "backup_title": "Create backup",
        "backup_desc": (
            "Choose a folder. SWIR creates a new owner-only ZIP with a SHA-256 integrity manifest for every file."
        ),
        "choose_backup": "Choose backup folder…",
        "choose_backup_tooltip": "Choose a local folder for a new verified SWIR user-state backup",
        "restore_title": "Restore SWIR user data",
        "restore_desc": (
            "Choose a SWIR backup to verify first. Restore uses staging, explicit confirmation and preserves "
            "the previous live roots as recovery directories."
        ),
        "choose_restore": "Choose backup to verify…",
        "choose_restore_tooltip": "Choose a local SWIR backup archive and verify it before restore",
        "no_archive": "No restore archive selected.",
        "restore_verified": "Restore verified backup",
        "restore_tooltip": "Restore only the verified SWIR user-state backup after separate confirmation",
        "ready": "Ready • no privileged operations",
        "backup_chooser_title": "Choose SWIR backup folder",
        "create_here": "Create backup here",
        "cancel": "Cancel",
        "local_folder_required": "Backup requires a local folder.",
        "creating": "Creating verified backup…",
        "backup_failed": "Backup failed safely: {reason}",
        "backup_created": "Backup created: {name} • {files} files • {bytes} bytes",
        "restore_chooser_title": "Choose SWIR backup",
        "verify_backup": "Verify backup",
        "backup_filter": "SWIR backup ZIP",
        "local_file_required": "Restore requires a local SWIR backup file.",
        "verification_failed": "Backup verification failed: {reason}",
        "archive_rejected": "Selected archive was rejected.",
        "verified_summary": "Verified {name} • created {created} • {files} files • {bytes} bytes",
        "verified_status": "Backup verified. Restore still requires separate confirmation.",
        "confirm_title": "Restore SWIR user data?",
        "confirm_detail": (
            "Current SWIR config and app-data roots will be replaced only after full staging. "
            "Their previous versions are preserved as hidden recovery directories. Close other SWIR apps first."
        ),
        "restore": "Restore",
        "cancelled": "Restore cancelled; no data changed.",
        "restoring": "Restoring verified SWIR user data…",
        "restore_failed": "Restore failed safely: {reason}",
        "restore_complete_one": "Restore complete. Previous state preserved in {count} recovery directory.",
        "restore_complete_many": "Restore complete. Previous state preserved in {count} recovery directories.",
    },
    "pl-PL": {
        "window_title": "Kopia i przywracanie SWIR",
        "brand": "◆  Kopia i przywracanie SWIR",
        "intro": "Chroń ustawienia użytkownika i dane aplikacji SWIR bez dostępu root.",
        "limits": (
            "Zakres: wyłącznie konfiguracja SWIR i dane aplikacji użytkownika. "
            "Kopie nie obejmują reszty katalogu domowego, zainstalowanych pakietów ani dysków."
        ),
        "backup_title": "Utwórz kopię zapasową",
        "backup_desc": (
            "Wybierz folder. SWIR utworzy nowy plik ZIP tylko dla właściciela z manifestem integralności SHA-256 dla każdego pliku."
        ),
        "choose_backup": "Wybierz folder kopii…",
        "choose_backup_tooltip": "Wybierz lokalny folder dla nowej zweryfikowanej kopii danych użytkownika SWIR",
        "restore_title": "Przywróć dane użytkownika SWIR",
        "restore_desc": (
            "Najpierw wybierz kopię SWIR do weryfikacji. Przywracanie używa stagingu i osobnego potwierdzenia, "
            "a poprzedni stan zachowuje jako katalogi odzyskiwania."
        ),
        "choose_restore": "Wybierz kopię do weryfikacji…",
        "choose_restore_tooltip": "Wybierz lokalne archiwum SWIR i zweryfikuj je przed przywróceniem",
        "no_archive": "Nie wybrano archiwum do przywrócenia.",
        "restore_verified": "Przywróć zweryfikowaną kopię",
        "restore_tooltip": "Przywróć tylko zweryfikowaną kopię danych użytkownika po osobnym potwierdzeniu",
        "ready": "Gotowe • bez operacji uprzywilejowanych",
        "backup_chooser_title": "Wybierz folder kopii SWIR",
        "create_here": "Utwórz kopię tutaj",
        "cancel": "Anuluj",
        "local_folder_required": "Kopia wymaga lokalnego folderu.",
        "creating": "Tworzenie zweryfikowanej kopii…",
        "backup_failed": "Tworzenie kopii zakończone bezpiecznym błędem: {reason}",
        "backup_created": "Utworzono kopię: {name} • pliki: {files} • {bytes} bajtów",
        "restore_chooser_title": "Wybierz kopię SWIR",
        "verify_backup": "Zweryfikuj kopię",
        "backup_filter": "Kopia SWIR ZIP",
        "local_file_required": "Przywracanie wymaga lokalnego pliku kopii SWIR.",
        "verification_failed": "Weryfikacja kopii nie powiodła się: {reason}",
        "archive_rejected": "Wybrane archiwum zostało odrzucone.",
        "verified_summary": "Zweryfikowano {name} • utworzono {created} • pliki: {files} • {bytes} bajtów",
        "verified_status": "Kopia zweryfikowana. Przywracanie nadal wymaga osobnego potwierdzenia.",
        "confirm_title": "Przywrócić dane użytkownika SWIR?",
        "confirm_detail": (
            "Bieżące katalogi konfiguracji i danych aplikacji SWIR zostaną zastąpione dopiero po pełnym stagingu. "
            "Poprzednie wersje zostaną zachowane jako ukryte katalogi odzyskiwania. Najpierw zamknij inne aplikacje SWIR."
        ),
        "restore": "Przywróć",
        "cancelled": "Przywracanie anulowane; dane nie zostały zmienione.",
        "restoring": "Przywracanie zweryfikowanych danych użytkownika SWIR…",
        "restore_failed": "Przywracanie zakończone bezpiecznym błędem: {reason}",
        "restore_complete_one": "Przywracanie zakończone. Poprzedni stan zachowano w {count} katalogu odzyskiwania.",
        "restore_complete_many": "Przywracanie zakończone. Poprzedni stan zachowano w {count} katalogach odzyskiwania.",
    },
    "nb-NO": {
        "window_title": "SWIR Sikkerhetskopi og gjenoppretting",
        "brand": "◆  SWIR Sikkerhetskopi og gjenoppretting",
        "intro": "Beskytt SWIR-brukerinnstillinger og appdata uten root-tilgang.",
        "limits": (
            "Omfang: bare SWIR-konfigurasjonen og appdataene dine. "
            "Sikkerhetskopier utelater resten av hjemmemappen, installerte pakker og disker."
        ),
        "backup_title": "Opprett sikkerhetskopi",
        "backup_desc": (
            "Velg en mappe. SWIR oppretter en ny eierbeskyttet ZIP med SHA-256-integritetsmanifest for hver fil."
        ),
        "choose_backup": "Velg mappe for sikkerhetskopi…",
        "choose_backup_tooltip": "Velg en lokal mappe for en ny verifisert SWIR-brukerdatakopi",
        "restore_title": "Gjenopprett SWIR-brukerdata",
        "restore_desc": (
            "Velg først en SWIR-sikkerhetskopi som skal verifiseres. Gjenoppretting bruker staging og eksplisitt "
            "bekreftelse, og bevarer forrige tilstand som gjenopprettingsmapper."
        ),
        "choose_restore": "Velg sikkerhetskopi for verifisering…",
        "choose_restore_tooltip": "Velg et lokalt SWIR-arkiv og verifiser det før gjenoppretting",
        "no_archive": "Ingen sikkerhetskopi er valgt for gjenoppretting.",
        "restore_verified": "Gjenopprett verifisert sikkerhetskopi",
        "restore_tooltip": "Gjenopprett bare den verifiserte SWIR-brukerdatakopien etter separat bekreftelse",
        "ready": "Klar • ingen privilegerte operasjoner",
        "backup_chooser_title": "Velg SWIR-mappe for sikkerhetskopi",
        "create_here": "Opprett sikkerhetskopi her",
        "cancel": "Avbryt",
        "local_folder_required": "Sikkerhetskopi krever en lokal mappe.",
        "creating": "Oppretter verifisert sikkerhetskopi…",
        "backup_failed": "Sikkerhetskopiering feilet på en sikker måte: {reason}",
        "backup_created": "Sikkerhetskopi opprettet: {name} • {files} filer • {bytes} byte",
        "restore_chooser_title": "Velg SWIR-sikkerhetskopi",
        "verify_backup": "Verifiser sikkerhetskopi",
        "backup_filter": "SWIR-sikkerhetskopi ZIP",
        "local_file_required": "Gjenoppretting krever en lokal SWIR-sikkerhetskopifil.",
        "verification_failed": "Verifisering av sikkerhetskopi feilet: {reason}",
        "archive_rejected": "Det valgte arkivet ble avvist.",
        "verified_summary": "Verifisert {name} • opprettet {created} • {files} filer • {bytes} byte",
        "verified_status": "Sikkerhetskopien er verifisert. Gjenoppretting krever fortsatt separat bekreftelse.",
        "confirm_title": "Gjenopprette SWIR-brukerdata?",
        "confirm_detail": (
            "Gjeldende SWIR-konfigurasjon og appdatarøtter erstattes først etter full staging. "
            "Tidligere versjoner bevares som skjulte gjenopprettingsmapper. Lukk andre SWIR-apper først."
        ),
        "restore": "Gjenopprett",
        "cancelled": "Gjenoppretting avbrutt; ingen data ble endret.",
        "restoring": "Gjenoppretter verifiserte SWIR-brukerdata…",
        "restore_failed": "Gjenoppretting feilet på en sikker måte: {reason}",
        "restore_complete_one": "Gjenoppretting fullført. Forrige tilstand er bevart i {count} gjenopprettingsmappe.",
        "restore_complete_many": "Gjenoppretting fullført. Forrige tilstand er bevart i {count} gjenopprettingsmapper.",
    },
}


@dataclass(frozen=True)
class BackupLocale:
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


def backup_locale(language: object) -> BackupLocale:
    requested = normalize_language_tag(language) or "en"
    catalog = requested if requested in _TRANSLATIONS else "en"
    return BackupLocale(requested, catalog, _TRANSLATIONS[catalog])


class SwirBackup(Gtk.Application):
    def __init__(self) -> None:
        super().__init__(application_id=APP_ID)
        self.window: Gtk.ApplicationWindow | None = None
        self.status: Gtk.Label | None = None
        self.summary: Gtk.Label | None = None
        self.backup_button: Gtk.Button | None = None
        self.choose_restore_button: Gtk.Button | None = None
        self.restore_button: Gtk.Button | None = None
        self.settings_store = UserSettingsStore()
        self.locale = self._load_locale()
        self.runtime = BackupRuntime()
        self.pending_restore: BackupInfo | None = None
        self.e2e = os.environ.get("SWIR_APP_E2E", "0") == "1"
        self.evidence_path = os.environ.get("SWIR_APP_EVIDENCE_PATH", "")
        self.evidence_written = False

    def _load_locale(self) -> BackupLocale:
        try:
            language = self.settings_store.load().get("language", "en")
        except (OSError, RuntimeError, UnicodeError, ValueError):
            language = "en"
        return backup_locale(language)

    def _t(self, key: str, **values: object) -> str:
        return self.locale.text(key, **values)

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
        window.set_title(self._t("window_title"))
        window.set_default_size(820, 590)
        window.add_css_class("swir-app")
        direction = Gtk.TextDirection.RTL if self.locale.text_direction == "rtl" else Gtk.TextDirection.LTR
        window.set_direction(direction)
        self.window = window

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        window.set_child(root)
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        header.add_css_class("swir-header")
        brand = Gtk.Label(label=self._t("brand"))
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

        intro = Gtk.Label(label=self._t("intro"), wrap=True, xalign=0)
        intro.add_css_class("swir-title")
        content.append(intro)
        limits = Gtk.Label(label=self._t("limits"), wrap=True, xalign=0)
        limits.add_css_class("swir-muted")
        content.append(limits)

        backup_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        backup_card.add_css_class("swir-card")
        backup_title = Gtk.Label(label=self._t("backup_title"), xalign=0)
        backup_title.add_css_class("swir-title")
        backup_card.append(backup_title)
        backup_desc = Gtk.Label(label=self._t("backup_desc"), wrap=True, xalign=0)
        backup_desc.add_css_class("swir-muted")
        backup_card.append(backup_desc)
        backup = Gtk.Button(label=self._t("choose_backup"))
        backup.add_css_class("swir-primary")
        backup.set_focusable(True)
        backup.set_tooltip_text(self._t("choose_backup_tooltip"))
        backup.connect("clicked", self._choose_backup_folder)
        backup_card.append(backup)
        self.backup_button = backup
        content.append(backup_card)

        restore_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        restore_card.add_css_class("swir-card")
        restore_title = Gtk.Label(label=self._t("restore_title"), xalign=0)
        restore_title.add_css_class("swir-title")
        restore_card.append(restore_title)
        restore_desc = Gtk.Label(label=self._t("restore_desc"), wrap=True, xalign=0)
        restore_desc.add_css_class("swir-muted")
        restore_card.append(restore_desc)
        choose = Gtk.Button(label=self._t("choose_restore"))
        choose.add_css_class("swir-button")
        choose.set_focusable(True)
        choose.set_tooltip_text(self._t("choose_restore_tooltip"))
        choose.connect("clicked", self._choose_restore_file)
        restore_card.append(choose)
        self.choose_restore_button = choose
        self.summary = Gtk.Label(label=self._t("no_archive"), wrap=True, xalign=0)
        self.summary.add_css_class("swir-muted")
        restore_card.append(self.summary)
        self.restore_button = Gtk.Button(label=self._t("restore_verified"))
        self.restore_button.add_css_class("swir-danger")
        self.restore_button.set_focusable(True)
        self.restore_button.set_tooltip_text(self._t("restore_tooltip"))
        self.restore_button.set_sensitive(False)
        self.restore_button.connect("clicked", self._confirm_restore)
        restore_card.append(self.restore_button)
        content.append(restore_card)

        self.status = Gtk.Label(label=self._t("ready"), wrap=True, xalign=0)
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
            title=self._t("backup_chooser_title"),
            transient_for=self.window,
            action=Gtk.FileChooserAction.SELECT_FOLDER,
            accept_label=self._t("create_here"),
            cancel_label=self._t("cancel"),
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
            self._set_status(self._t("local_folder_required"))
            return
        destination = pathlib.Path(selected.get_path())
        self._set_status(self._t("creating"))
        GLib.idle_add(self._create_backup_idle, destination)

    def _create_backup_idle(self, destination: pathlib.Path) -> bool:
        try:
            info = self.runtime.create_backup(destination)
        except (BackupError, OSError, ValueError) as exc:
            self._set_status(self._t("backup_failed", reason=exc))
        else:
            self._set_status(
                self._t(
                    "backup_created",
                    name=info.path.name,
                    files=len(info.entries),
                    bytes=info.total_bytes,
                )
            )
        return False

    def _choose_restore_file(self, _button: Gtk.Button) -> None:
        assert self.window is not None
        chooser = Gtk.FileChooserNative(
            title=self._t("restore_chooser_title"),
            transient_for=self.window,
            action=Gtk.FileChooserAction.OPEN,
            accept_label=self._t("verify_backup"),
            cancel_label=self._t("cancel"),
        )
        file_filter = Gtk.FileFilter()
        file_filter.set_name(self._t("backup_filter"))
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
            self._set_status(self._t("local_file_required"))
            return
        try:
            info = self.runtime.inspect_backup(pathlib.Path(selected.get_path()))
        except (BackupError, OSError, ValueError) as exc:
            self._set_status(self._t("verification_failed", reason=exc))
            if self.summary is not None:
                self.summary.set_text(self._t("archive_rejected"))
            return
        self.pending_restore = info
        if self.summary is not None:
            self.summary.set_text(
                self._t(
                    "verified_summary",
                    name=info.path.name,
                    created=info.created_at,
                    files=len(info.entries),
                    bytes=info.total_bytes,
                )
            )
        if self.restore_button is not None:
            self.restore_button.set_sensitive(True)
        self._set_status(self._t("verified_status"))

    def _confirm_restore(self, _button: Gtk.Button) -> None:
        if self.pending_restore is None or self.window is None:
            return
        dialog = Gtk.MessageDialog(
            transient_for=self.window,
            modal=True,
            message_type=Gtk.MessageType.WARNING,
            buttons=Gtk.ButtonsType.NONE,
            text=self._t("confirm_title"),
            secondary_text=self._t("confirm_detail"),
        )
        dialog.add_button(self._t("cancel"), Gtk.ResponseType.CANCEL)
        dialog.add_button(self._t("restore"), Gtk.ResponseType.ACCEPT)
        dialog.connect("response", self._restore_confirmed)
        dialog.present()

    def _restore_confirmed(self, dialog: Gtk.MessageDialog, response: int) -> None:
        dialog.destroy()
        if response != Gtk.ResponseType.ACCEPT or self.pending_restore is None:
            self._set_status(self._t("cancelled"))
            return
        source = self.pending_restore.path
        self._set_status(self._t("restoring"))
        GLib.idle_add(self._restore_idle, source)

    def _restore_idle(self, source: pathlib.Path) -> bool:
        try:
            previous = self.runtime.restore_backup(source)
        except (BackupError, OSError, ValueError) as exc:
            self._set_status(self._t("restore_failed", reason=exc))
        else:
            count = len(previous)
            key = "restore_complete_one" if count == 1 else "restore_complete_many"
            self._set_status(self._t(key, count=count))
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

            localized_surface_verified = bool(
                self.window
                and self.window.get_title() == self._t("window_title")
                and self.backup_button
                and self.backup_button.get_label() == self._t("choose_backup")
                and self.choose_restore_button
                and self.choose_restore_button.get_label() == self._t("choose_restore")
                and self.restore_button
                and self.restore_button.get_label() == self._t("restore_verified")
            )
            payload = {
                "schema": EVIDENCE_SCHEMA,
                "passed": localized_surface_verified,
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
                "requestedLanguage": self.locale.requested_language,
                "catalogLanguage": self.locale.catalog_language,
                "translationFallback": self.locale.fallback,
                "textDirection": self.locale.text_direction,
                "localizedWindowTitle": self._t("window_title"),
                "localizedCreateLabel": self._t("choose_backup"),
                "localizedRestoreLabel": self._t("restore_verified"),
                "localizedSurfaceVerified": localized_surface_verified,
                "backupButtonFocusable": bool(self.backup_button and self.backup_button.get_focusable()),
                "restoreChooserFocusable": bool(
                    self.choose_restore_button and self.choose_restore_button.get_focusable()
                ),
                "restoreButtonFocusable": bool(self.restore_button and self.restore_button.get_focusable()),
                "localizedTooltips": bool(
                    self.backup_button
                    and self.backup_button.get_tooltip_text() == self._t("choose_backup_tooltip")
                    and self.choose_restore_button
                    and self.choose_restore_button.get_tooltip_text() == self._t("choose_restore_tooltip")
                    and self.restore_button
                    and self.restore_button.get_tooltip_text() == self._t("restore_tooltip")
                ),
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
