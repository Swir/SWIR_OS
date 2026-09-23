#!/usr/bin/env python3
"""SWIR Software Center — native package discovery and brokered installs.

Package discovery remains unprivileged and bounded. Mutations never execute APT,
pkexec, sudo or arbitrary commands from this GTK process: an install first asks
the SWIR package broker for an exact preview, displays that plan for explicit
confirmation, then requests peer-bound Polkit authorization and commits the same
single-use plan through the journaled transaction service.

A trusted caller may pass ``--install <package>`` to preselect one package. That
request never auto-commits: it enters the exact same preview -> explicit user
confirmation -> Polkit -> journaled transaction flow as an Install button.

The visible UI follows the bounded SWIR per-user language preference for
English, Polish and Norwegian Bokmål with a reviewed English fallback.
"""

from __future__ import annotations

import json
import os
import pathlib
import re
import shlex
import sys
import threading
from typing import Final, Mapping

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gdk, GLib, Gtk  # noqa: E402

LIBDIR = pathlib.Path("/usr/local/lib/swir")
if LIBDIR.is_dir() and str(LIBDIR) not in sys.path:
    sys.path.insert(0, str(LIBDIR))

from core_runtime import UserSettingsStore, normalize_language_tag  # noqa: E402
from package_mutation_flow import PackageMutationFlow, PackageMutationIntent  # noqa: E402
from package_status_runtime import (  # noqa: E402
    MAX_PACKAGE_ROWS,
    PackageRow,
    list_installed,
    normalize_search_term,
    search_available,
    tools_status,
)
from package_transaction_client import PackageBrokerError, PackageTransactionClient  # noqa: E402

APP_ID: Final = "dev.swir.SoftwareCenter"
EVIDENCE_SCHEMA: Final = "swir.native-software-center-runtime-evidence/0.2"
PACKAGE_NAME_RE: Final = re.compile(r"^[a-z0-9][a-z0-9+.-]{0,127}$")

CSS = b"""
window.swir-app { background: #02050A; color: #F4FAFF; }
.swir-header { background: #07111C; border-bottom: 1px solid #0088FF; padding: 10px 14px; }
.swir-brand { color: #62E5FF; font-size: 18px; font-weight: 800; }
.swir-muted { color: #8DA8B8; }
.swir-status { background: #07111C; border: 1px solid rgba(98,229,255,0.28); border-radius: 12px; padding: 9px 12px; }
.swir-row { padding: 8px 10px; border-bottom: 1px solid rgba(98,229,255,0.08); }
.swir-name { color: #EAF9FF; font-weight: 700; }
.swir-button { background: #07111C; color: #F4FAFF; border: 1px solid #0088FF; border-radius: 10px; padding: 7px 12px; }
.swir-button:hover { border-color: #62E5FF; }
.swir-primary { background: #0088FF; color: #F4FAFF; border-radius: 10px; padding: 7px 14px; font-weight: 700; }
entry { background: #07111C; color: #F4FAFF; border: 1px solid rgba(98,229,255,0.35); border-radius: 10px; padding: 7px 10px; }
"""

_TRANSLATIONS: Final[Mapping[str, Mapping[str, str]]] = {
    "en": {
        "window_title": "SWIR Software Center",
        "brand": "◆  SWIR Software Center",
        "installed": "Installed",
        "installed_tooltip": "Show packages installed on this SWIR system",
        "search_placeholder": "Search local package metadata",
        "search": "Search",
        "search_tooltip": "Search the bounded local package metadata index",
        "loading": "Loading installed packages…",
        "footer": "Installs use SWIR preview → explicit confirmation → Polkit → journaled transaction. This app never runs privileged package commands directly.",
        "trusted_request": "Trusted install request received for {package}; preparing preview…",
        "broker_suffix": " • package mutation broker unavailable",
        "install": "Install",
        "install_tooltip": "Preview and confirm a journaled SWIR package transaction",
        "broker_tooltip": "SWIR package transaction broker is not available",
        "busy": "A package transaction is already in progress.",
        "metadata_unavailable": "Package metadata unavailable: {error}",
        "installed_noun": "installed packages",
        "search_noun": "search results",
        "showing_first": " (showing first {limit})",
        "rows_status": "{count} {noun}{suffix}",
        "searching": "Searching for “{term}”…",
        "invalid_search": "Search request is invalid; no package operation was started.",
        "invalid_request": "Invalid package request; no changes were made.",
        "broker_unavailable": "SWIR package transaction broker is unavailable; no changes were made.",
        "preparing": "Preparing trusted install preview for {package}…",
        "confirm_title": "Confirm package installation",
        "cancel": "Cancel",
        "question": "Install {package}?",
        "system_provider": "system provider",
        "package_manager": "Package manager: {manager}",
        "plan_digest": "Plan digest: {digest}",
        "command_preview": "Broker command preview (display only):\n{command}",
        "confirm_note": "Continuing requests Polkit authorization and commits exactly this preview. If the plan changes, the transaction fails closed and must be previewed again.",
        "waiting": "Waiting for confirmation to install {package}.",
        "cancelled": "Installation cancelled before authorization; no changes were made.",
        "authorizing": "Authorizing and installing {package}…",
        "committed": "Package transaction committed and verified. Transaction: {transaction}",
        "stopped": "Package transaction stopped ({code}): {message}",
    },
    "pl-PL": {
        "window_title": "Centrum oprogramowania SWIR",
        "brand": "◆  Centrum oprogramowania SWIR",
        "installed": "Zainstalowane",
        "installed_tooltip": "Pokaż pakiety zainstalowane w tym systemie SWIR",
        "search_placeholder": "Przeszukaj lokalne metadane pakietów",
        "search": "Szukaj",
        "search_tooltip": "Przeszukaj ograniczony lokalny indeks metadanych pakietów",
        "loading": "Wczytywanie zainstalowanych pakietów…",
        "footer": "Instalacje używają ścieżki SWIR: podgląd → jawne potwierdzenie → Polkit → transakcja z dziennikiem. Aplikacja nigdy nie uruchamia bezpośrednio uprzywilejowanych poleceń pakietów.",
        "trusted_request": "Odebrano zaufane żądanie instalacji {package}; przygotowywanie podglądu…",
        "broker_suffix": " • broker modyfikacji pakietów jest niedostępny",
        "install": "Zainstaluj",
        "install_tooltip": "Wyświetl podgląd i potwierdź rejestrowaną transakcję pakietu SWIR",
        "broker_tooltip": "Broker transakcji pakietów SWIR jest niedostępny",
        "busy": "Transakcja pakietu jest już w toku.",
        "metadata_unavailable": "Metadane pakietów są niedostępne: {error}",
        "installed_noun": "zainstalowanych pakietów",
        "search_noun": "wyników wyszukiwania",
        "showing_first": " (pokazano pierwsze {limit})",
        "rows_status": "{count} {noun}{suffix}",
        "searching": "Wyszukiwanie „{term}”…",
        "invalid_search": "Żądanie wyszukiwania jest nieprawidłowe; nie rozpoczęto operacji na pakietach.",
        "invalid_request": "Nieprawidłowe żądanie pakietu; nie wprowadzono zmian.",
        "broker_unavailable": "Broker transakcji pakietów SWIR jest niedostępny; nie wprowadzono zmian.",
        "preparing": "Przygotowywanie zaufanego podglądu instalacji {package}…",
        "confirm_title": "Potwierdź instalację pakietu",
        "cancel": "Anuluj",
        "question": "Zainstalować {package}?",
        "system_provider": "dostawca systemowy",
        "package_manager": "Menedżer pakietów: {manager}",
        "plan_digest": "Skrót planu: {digest}",
        "command_preview": "Podgląd polecenia brokera (tylko do wyświetlenia):\n{command}",
        "confirm_note": "Kontynuacja żąda autoryzacji Polkit i zatwierdza dokładnie ten podgląd. Jeśli plan się zmieni, transakcja zostanie bezpiecznie odrzucona i trzeba ponownie wygenerować podgląd.",
        "waiting": "Oczekiwanie na potwierdzenie instalacji {package}.",
        "cancelled": "Instalację anulowano przed autoryzacją; nie wprowadzono zmian.",
        "authorizing": "Autoryzacja i instalowanie {package}…",
        "committed": "Transakcja pakietu została zatwierdzona i zweryfikowana. Transakcja: {transaction}",
        "stopped": "Transakcja pakietu zatrzymana ({code}): {message}",
    },
    "nb-NO": {
        "window_title": "SWIR programvaresenter",
        "brand": "◆  SWIR programvaresenter",
        "installed": "Installert",
        "installed_tooltip": "Vis pakker som er installert på dette SWIR-systemet",
        "search_placeholder": "Søk i lokale pakkemetadata",
        "search": "Søk",
        "search_tooltip": "Søk i den avgrensede lokale indeksen for pakkemetadata",
        "loading": "Laster installerte pakker…",
        "footer": "Installasjoner bruker SWIR-forhåndsvisning → eksplisitt bekreftelse → Polkit → journalført transaksjon. Appen kjører aldri privilegerte pakkekommandoer direkte.",
        "trusted_request": "Mottok klarert installasjonsforespørsel for {package}; forbereder forhåndsvisning…",
        "broker_suffix": " • brokeren for pakkeendringer er utilgjengelig",
        "install": "Installer",
        "install_tooltip": "Forhåndsvis og bekreft en journalført SWIR-pakketransaksjon",
        "broker_tooltip": "SWIR-brokeren for pakketransaksjoner er ikke tilgjengelig",
        "busy": "En pakketransaksjon pågår allerede.",
        "metadata_unavailable": "Pakkemetadata er utilgjengelige: {error}",
        "installed_noun": "installerte pakker",
        "search_noun": "søkeresultater",
        "showing_first": " (viser de første {limit})",
        "rows_status": "{count} {noun}{suffix}",
        "searching": "Søker etter «{term}»…",
        "invalid_search": "Søkeforespørselen er ugyldig; ingen pakkeoperasjon ble startet.",
        "invalid_request": "Ugyldig pakkeforespørsel; ingen endringer ble gjort.",
        "broker_unavailable": "SWIR-brokeren for pakketransaksjoner er utilgjengelig; ingen endringer ble gjort.",
        "preparing": "Forbereder klarert installasjonsoversikt for {package}…",
        "confirm_title": "Bekreft pakkeinstallasjon",
        "cancel": "Avbryt",
        "question": "Installere {package}?",
        "system_provider": "systemleverandør",
        "package_manager": "Pakkebehandler: {manager}",
        "plan_digest": "Plansammendrag: {digest}",
        "command_preview": "Forhåndsvisning av brokerkommando (kun visning):\n{command}",
        "confirm_note": "Fortsettelse ber om Polkit-autorisasjon og utfører nøyaktig denne forhåndsvisningen. Hvis planen endres, feiler transaksjonen lukket og må forhåndsvises på nytt.",
        "waiting": "Venter på bekreftelse for å installere {package}.",
        "cancelled": "Installasjonen ble avbrutt før autorisasjon; ingen endringer ble gjort.",
        "authorizing": "Autoriserer og installerer {package}…",
        "committed": "Pakketransaksjonen er utført og verifisert. Transaksjon: {transaction}",
        "stopped": "Pakketransaksjonen stoppet ({code}): {message}",
    },
}


def _locale_key(language: object) -> str:
    normalized = normalize_language_tag(language)
    return normalized if normalized in {"pl-PL", "nb-NO"} else "en"


def resolve_locale(settings_store: UserSettingsStore | None = None) -> tuple[str, str]:
    """Resolve the bounded per-user language with a fail-safe English fallback."""
    try:
        profile = (settings_store or UserSettingsStore()).load()
        requested = normalize_language_tag(profile.get("language", ""))
    except (KeyError, OSError, RuntimeError, TypeError, ValueError):
        requested = ""
    return _locale_key(requested), requested or "en"


def tr(locale: str, key: str, **values: object) -> str:
    catalog = _TRANSLATIONS.get(locale, _TRANSLATIONS["en"])
    template = catalog.get(key, _TRANSLATIONS["en"].get(key, key))
    return template.format(**values) if values else template


def parse_install_request(argv: list[str]) -> tuple[str | None, list[str]]:
    """Remove SWIR's fixed install request from GTK argv without executing it."""
    args = list(argv)
    if "--install" not in args[1:]:
        return None, args
    index = args.index("--install", 1)
    if index + 1 >= len(args):
        raise ValueError("--install requires a package name")
    package = args[index + 1]
    if not PACKAGE_NAME_RE.fullmatch(package):
        raise ValueError("invalid package name")
    clean = args[:index] + args[index + 2 :]
    if len(clean) != 1:
        raise ValueError("unexpected arguments after --install request")
    return package, clean


class SwirSoftwareCenter(Gtk.Application):
    def __init__(self, requested_install: str | None = None) -> None:
        super().__init__(application_id=APP_ID)
        self.locale, self.requested_language = resolve_locale()
        self.requested_install = requested_install
        self.request_dispatched = False
        self.window: Gtk.ApplicationWindow | None = None
        self.listbox: Gtk.ListBox | None = None
        self.status_label: Gtk.Label | None = None
        self.search_entry: Gtk.Entry | None = None
        self.generation = 0
        self.mode = "installed"
        self.visible_rows = 0
        self.last_query_ok = False
        self.mutation_busy = False
        self.last_transaction_state = "none"
        self.package_client = PackageTransactionClient()
        self.mutation_flow = PackageMutationFlow(self.package_client)
        self.e2e = os.environ.get("SWIR_APP_E2E", "0") == "1"
        self.evidence_path = os.environ.get("SWIR_APP_EVIDENCE_PATH", "")

    def do_startup(self) -> None:
        Gtk.Application.do_startup(self)
        provider = Gtk.CssProvider()
        provider.load_from_data(CSS)
        display = Gdk.Display.get_default()
        if display is None:
            raise RuntimeError("SWIR Software Center requires a graphical display")
        Gtk.StyleContext.add_provider_for_display(display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    def do_activate(self) -> None:
        if self.window is not None:
            self.window.present()
            return
        window = Gtk.ApplicationWindow(application=self)
        window.set_title(tr(self.locale, "window_title"))
        window.set_default_size(1040, 720)
        window.add_css_class("swir-app")
        self.window = window
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        window.set_child(root)
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        header.add_css_class("swir-header")
        brand = Gtk.Label(label=tr(self.locale, "brand"))
        brand.add_css_class("swir-brand")
        brand.set_xalign(0)
        header.append(brand)
        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        header.append(spacer)
        installed = Gtk.Button(label=tr(self.locale, "installed"))
        installed.add_css_class("swir-button")
        installed.set_tooltip_text(tr(self.locale, "installed_tooltip"))
        installed.connect("clicked", self._installed_clicked)
        header.append(installed)
        root.append(header)
        search_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        search_row.set_margin_start(12)
        search_row.set_margin_end(12)
        self.search_entry = Gtk.Entry()
        self.search_entry.set_hexpand(True)
        self.search_entry.set_placeholder_text(tr(self.locale, "search_placeholder"))
        self.search_entry.set_tooltip_text(tr(self.locale, "search_placeholder"))
        self.search_entry.set_max_length(64)
        self.search_entry.connect("activate", self._search_entry_activated)
        search_row.append(self.search_entry)
        search = Gtk.Button(label=tr(self.locale, "search"))
        search.add_css_class("swir-button")
        search.set_tooltip_text(tr(self.locale, "search_tooltip"))
        search.connect("clicked", self._search_clicked)
        search_row.append(search)
        root.append(search_row)
        self.status_label = Gtk.Label(label=tr(self.locale, "loading"), wrap=True)
        self.status_label.set_xalign(0)
        self.status_label.set_margin_start(12)
        self.status_label.set_margin_end(12)
        self.status_label.add_css_class("swir-status")
        root.append(self.status_label)
        scroller = Gtk.ScrolledWindow()
        scroller.set_hexpand(True)
        scroller.set_vexpand(True)
        self.listbox = Gtk.ListBox()
        self.listbox.set_selection_mode(Gtk.SelectionMode.NONE)
        scroller.set_child(self.listbox)
        root.append(scroller)
        footer = Gtk.Label(label=tr(self.locale, "footer"), wrap=True)
        footer.add_css_class("swir-muted")
        footer.set_xalign(0)
        footer.set_margin_start(12)
        footer.set_margin_end(12)
        footer.set_margin_bottom(8)
        root.append(footer)
        window.connect("map", self._on_mapped)
        window.present()
        if self.requested_install:
            self.search_entry.set_text(self.requested_install)
            self.status_label.set_text(tr(self.locale, "trusted_request", package=self.requested_install))
            GLib.idle_add(self._dispatch_requested_install)
        else:
            self._load_installed()

    def _dispatch_requested_install(self) -> bool:
        if self.request_dispatched or not self.requested_install:
            return False
        self.request_dispatched = True
        self._prepare_mutation("install", self.requested_install)
        return False

    def _clear_rows(self) -> None:
        assert self.listbox is not None
        child = self.listbox.get_first_child()
        while child is not None:
            next_child = child.get_next_sibling()
            self.listbox.remove(child)
            child = next_child

    def _render_rows(self, rows: list[PackageRow], *, message: str) -> None:
        assert self.listbox is not None and self.status_label is not None
        self._clear_rows()
        self.visible_rows = len(rows)
        broker_available = self.mutation_flow.available()
        broker_suffix = "" if broker_available else tr(self.locale, "broker_suffix")
        self.status_label.set_text(f"{message}{broker_suffix}")
        for package in rows:
            row = Gtk.ListBoxRow()
            row.add_css_class("swir-row")
            outer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            box.set_hexpand(True)
            name = Gtk.Label(label=package.name)
            name.add_css_class("swir-name")
            name.set_xalign(0)
            name.set_selectable(True)
            box.append(name)
            detail_text = package.version
            if package.description:
                detail_text = f"{package.version}  •  {package.description}"
            detail = Gtk.Label(label=detail_text, ellipsize=3)
            detail.add_css_class("swir-muted")
            detail.set_xalign(0)
            detail.set_tooltip_text(detail_text)
            box.append(detail)
            outer.append(box)
            if self.mode == "search":
                install = Gtk.Button(label=tr(self.locale, "install"))
                install.add_css_class("swir-primary")
                install.set_sensitive(broker_available and not self.mutation_busy)
                install.set_tooltip_text(
                    tr(self.locale, "install_tooltip") if broker_available else tr(self.locale, "broker_tooltip")
                )
                install.connect("clicked", self._install_clicked, package.name)
                outer.append(install)
            row.set_child(outer)
            self.listbox.append(row)

    def _begin_query(self, worker, *, mode: str, pending: str) -> None:
        assert self.status_label is not None
        if self.mutation_busy:
            self.status_label.set_text(tr(self.locale, "busy"))
            return
        self.generation += 1
        generation = self.generation
        self.mode = mode
        self.status_label.set_text(pending)

        def run() -> None:
            try:
                rows, ok, error = worker()
            except (OSError, ValueError) as exc:
                rows, ok, error = [], False, str(exc)
            GLib.idle_add(self._finish_query, generation, rows, ok, error, mode)

        threading.Thread(target=run, name=f"swir-software-{mode}", daemon=True).start()

    def _finish_query(self, generation: int, rows: list[PackageRow], ok: bool, error: str, mode: str) -> bool:
        if generation != self.generation:
            return False
        self.last_query_ok = ok
        if not ok:
            self._render_rows([], message=tr(self.locale, "metadata_unavailable", error=error))
            return False
        noun = tr(self.locale, "installed_noun") if mode == "installed" else tr(self.locale, "search_noun")
        suffix = tr(self.locale, "showing_first", limit=MAX_PACKAGE_ROWS) if len(rows) >= MAX_PACKAGE_ROWS else ""
        self._render_rows(rows, message=tr(self.locale, "rows_status", count=len(rows), noun=noun, suffix=suffix))
        return False

    def _load_installed(self) -> None:
        self._begin_query(lambda: list_installed(), mode="installed", pending=tr(self.locale, "loading"))

    def _installed_clicked(self, _button: Gtk.Button) -> None:
        self._load_installed()

    def _search_entry_activated(self, _entry: Gtk.Entry) -> None:
        self._start_search()

    def _search_clicked(self, _button: Gtk.Button) -> None:
        self._start_search()

    def _start_search(self) -> None:
        assert self.search_entry is not None and self.status_label is not None
        try:
            term = normalize_search_term(self.search_entry.get_text())
        except ValueError:
            self.status_label.set_text(tr(self.locale, "invalid_search"))
            return
        self._begin_query(lambda: search_available(term), mode="search", pending=tr(self.locale, "searching", term=term))

    def _install_clicked(self, _button: Gtk.Button, package_name: str) -> None:
        self._prepare_mutation("install", package_name)

    def _prepare_mutation(self, operation: str, package_name: str) -> None:
        assert self.status_label is not None
        if self.mutation_busy:
            self.status_label.set_text(tr(self.locale, "busy"))
            return
        if not PACKAGE_NAME_RE.fullmatch(package_name):
            self.status_label.set_text(tr(self.locale, "invalid_request"))
            return
        if not self.mutation_flow.available():
            self.status_label.set_text(tr(self.locale, "broker_unavailable"))
            return
        self.mutation_busy = True
        self.last_transaction_state = "previewing"
        self.status_label.set_text(tr(self.locale, "preparing", package=package_name))

        def run() -> None:
            try:
                intent = self.mutation_flow.prepare(operation, package_name)
                GLib.idle_add(self._show_confirmation, intent)
            except PackageBrokerError as exc:
                GLib.idle_add(self._mutation_failed, exc.code, str(exc))

        threading.Thread(target=run, name="swir-software-preview", daemon=True).start()

    def _show_confirmation(self, intent: PackageMutationIntent) -> bool:
        assert self.window is not None and self.status_label is not None
        preview = intent.preview
        self.last_transaction_state = "awaiting-confirmation"
        command = shlex.join(preview.command_preview)
        if len(command) > 900:
            command = f"{command[:897]}…"
        dialog = Gtk.Dialog(transient_for=self.window, modal=True)
        dialog.set_title(tr(self.locale, "confirm_title"))
        dialog.add_button(tr(self.locale, "cancel"), Gtk.ResponseType.CANCEL)
        confirm = dialog.add_button(tr(self.locale, "install"), Gtk.ResponseType.OK)
        confirm.add_css_class("suggested-action")
        area = dialog.get_content_area()
        area.set_spacing(10)
        area.set_margin_top(16)
        area.set_margin_bottom(16)
        area.set_margin_start(18)
        area.set_margin_end(18)
        title = Gtk.Label(label=tr(self.locale, "question", package=preview.package_name), wrap=True)
        title.add_css_class("swir-name")
        title.set_xalign(0)
        area.append(title)
        manager = preview.package_manager or tr(self.locale, "system_provider")
        detail = Gtk.Label(
            label=(
                f"{tr(self.locale, 'package_manager', manager=manager)}\n"
                f"{tr(self.locale, 'plan_digest', digest=preview.plan_digest)}\n\n"
                f"{tr(self.locale, 'command_preview', command=command)}\n\n"
                f"{tr(self.locale, 'confirm_note')}"
            ),
            wrap=True,
            selectable=True,
        )
        detail.set_xalign(0)
        area.append(detail)
        dialog.connect("response", self._confirmation_response, intent)
        dialog.present()
        self.status_label.set_text(tr(self.locale, "waiting", package=preview.package_name))
        return False

    def _confirmation_response(self, dialog: Gtk.Dialog, response: int, intent: PackageMutationIntent) -> None:
        dialog.close()
        assert self.status_label is not None
        if response != Gtk.ResponseType.OK:
            self.mutation_busy = False
            self.last_transaction_state = "cancelled"
            self.status_label.set_text(tr(self.locale, "cancelled"))
            return
        self.last_transaction_state = "authorizing"
        self.status_label.set_text(tr(self.locale, "authorizing", package=intent.preview.package_name))

        def run() -> None:
            try:
                transaction = self.mutation_flow.commit(intent, intent.confirmation_digest)
                GLib.idle_add(self._mutation_committed, transaction)
            except PackageBrokerError as exc:
                GLib.idle_add(self._mutation_failed, exc.code, str(exc))

        threading.Thread(target=run, name="swir-software-commit", daemon=True).start()

    def _mutation_committed(self, transaction: dict) -> bool:
        assert self.status_label is not None
        self.mutation_busy = False
        self.last_transaction_state = str(transaction.get("state") or "committed")
        transaction_id = str(transaction.get("id") or "unknown")
        self.status_label.set_text(tr(self.locale, "committed", transaction=transaction_id))
        self._load_installed()
        return False

    def _mutation_failed(self, code: str, message: str) -> bool:
        assert self.status_label is not None
        self.mutation_busy = False
        self.last_transaction_state = "failed"
        self.status_label.set_text(tr(self.locale, "stopped", code=code, message=message))
        return False

    def _on_mapped(self, _window: Gtk.Window) -> None:
        if not self.e2e or not self.evidence_path:
            return
        path = pathlib.Path(self.evidence_path)
        runtime_text = os.environ.get("XDG_RUNTIME_DIR", "")
        if not runtime_text or path.parent.resolve() != pathlib.Path(runtime_text).resolve():
            raise RuntimeError("refusing Software Center evidence path outside XDG_RUNTIME_DIR")
        status = tools_status()
        broker_available = self.mutation_flow.available()
        payload = {
            "schema": EVIDENCE_SCHEMA,
            "passed": status["aptCache"] and status["dpkgQuery"],
            "applicationId": APP_ID,
            "nativeToolkit": "gtk4",
            "displayProtocol": "wayland",
            "windowMapped": True,
            "privilegedOperationsInUi": False,
            "mutationFlowWired": True,
            "mutationControlsExposed": broker_available,
            "packageBrokerAvailable": broker_available,
            "explicitPlanConfirmationRequired": True,
            "directPackageToolMutation": False,
            "packageTransactionBrokerBypassed": False,
            "readOnlyMetadata": True,
            "packageRowsBounded": MAX_PACKAGE_ROWS,
            "externalInstallRequestSupported": True,
            "externalInstallAutoCommit": False,
            "catalogLanguage": self.locale,
            "requestedLanguage": self.requested_language,
            "tools": status,
        }
        path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
        path.chmod(0o600)
        GLib.timeout_add(350, self._finish_e2e)

    def _finish_e2e(self) -> bool:
        self.quit()
        return False


def run_self_test() -> int:
    english_keys = set(_TRANSLATIONS["en"])
    assert english_keys
    for language in ("pl-PL", "nb-NO"):
        assert set(_TRANSLATIONS[language]) == english_keys
    assert _locale_key("pl_PL.UTF-8") == "pl-PL"
    assert _locale_key("nb_NO.UTF-8") == "nb-NO"
    assert _locale_key("de-DE") == "en"
    assert tr("unsupported", "install") == "Install"
    assert tr("pl-PL", "search") == "Szukaj"
    assert tr("nb-NO", "cancel") == "Avbryt"

    package, argv = parse_install_request(["swir-software-center", "--install", "firefox-esr"])
    assert package == "firefox-esr" and argv == ["swir-software-center"]
    for invalid in ("../bad", "Bad", "x y", ""):
        try:
            parse_install_request(["swir-software-center", "--install", invalid])
        except ValueError:
            pass
        else:
            raise AssertionError(f"invalid package accepted: {invalid!r}")
    print(json.dumps({"schema": "swir.software-center-request-selftest/0.2", "valid": True, "locales": ["en", "pl-PL", "nb-NO"]}))
    return 0


if __name__ == "__main__":
    if "--self-test" in sys.argv[1:]:
        raise SystemExit(run_self_test())
    try:
        requested, gtk_argv = parse_install_request(sys.argv)
    except ValueError as exc:
        print(f"SWIR Software Center: {exc}", file=sys.stderr)
        raise SystemExit(64)
    raise SystemExit(SwirSoftwareCenter(requested_install=requested).run(gtk_argv))
