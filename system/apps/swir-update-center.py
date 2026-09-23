#!/usr/bin/env python3
"""SWIR Update Center — native preview plus brokered per-package updates.

The list is derived from a non-mutating APT simulation. Applying one selected
update never invokes APT/pkexec/sudo from the GTK process: SWIR's package broker
creates an exact dependency-aware preview, the user explicitly confirms that
plan, Polkit authorizes the peer, and the journaled transaction service commits
and verifies it. Bulk upgrade remains intentionally unavailable until it has an
equally strict broker contract.

The visible UI follows the bounded SWIR per-user language preference for
English, Polish and Norwegian Bokmål with a reviewed English fallback.
"""

from __future__ import annotations

import json
import os
import pathlib
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
from package_status_runtime import MAX_UPDATE_ROWS, UpdateSnapshot, read_update_snapshot, tools_status  # noqa: E402
from package_transaction_client import PackageBrokerError, PackageTransactionClient  # noqa: E402

APP_ID: Final = "dev.swir.UpdateCenter"
EVIDENCE_SCHEMA: Final = "swir.native-update-center-runtime-evidence/0.2"

CSS = b"""
window.swir-app { background: #02050A; color: #F4FAFF; }
.swir-header { background: #07111C; border-bottom: 1px solid #0088FF; padding: 10px 14px; }
.swir-brand { color: #62E5FF; font-size: 18px; font-weight: 800; }
.swir-muted { color: #8DA8B8; }
.swir-status { background: #07111C; border: 1px solid rgba(98,229,255,0.28); border-radius: 12px; padding: 10px 14px; }
.swir-row { padding: 8px 10px; border-bottom: 1px solid rgba(98,229,255,0.08); }
.swir-name { color: #EAF9FF; font-weight: 700; }
.swir-button { background: #07111C; color: #F4FAFF; border: 1px solid #0088FF; border-radius: 10px; padding: 7px 12px; }
.swir-button:hover { border-color: #62E5FF; }
.swir-primary { background: #0088FF; color: #F4FAFF; border-radius: 10px; padding: 7px 14px; font-weight: 700; }
"""

_TRANSLATIONS: Final[Mapping[str, Mapping[str, str]]] = {
    "en": {
        "window_title": "SWIR Update Center",
        "brand": "◆  SWIR Update Center",
        "refresh": "Re-check local metadata",
        "refresh_tooltip": "Recalculate the update preview from local package metadata",
        "calculating": "Calculating a non-destructive update preview…",
        "explanation": "The list uses local package metadata only. Each Update button requests a fresh SWIR broker preview; no repository refresh or privileged command is performed by this app.",
        "footer": "Per-package updates use preview → explicit confirmation → Polkit → journaled transaction. Bulk upgrade and rollback controls remain unavailable until separately verified.",
        "busy": "A package transaction is already in progress.",
        "preview_unavailable": "Update preview unavailable: {message}",
        "broker_suffix": " • package mutation broker unavailable",
        "truncated_suffix": " • first {limit} shown",
        "rows_status": "{count} package upgrades in the local simulation{truncated}{broker}",
        "update": "Update",
        "update_tooltip": "Preview and confirm this package update through SWIR",
        "broker_tooltip": "SWIR package transaction broker is not available",
        "broker_unavailable": "SWIR package transaction broker is unavailable; no changes were made.",
        "preparing": "Preparing trusted update preview for {package}…",
        "confirm_title": "Confirm package update",
        "cancel": "Cancel",
        "question": "Update {package}?",
        "system_provider": "system provider",
        "package_manager": "Package manager: {manager}",
        "plan_digest": "Plan digest: {digest}",
        "command_preview": "Broker command preview (display only):\n{command}",
        "confirm_note": "Continuing requests Polkit authorization and commits exactly this preview. If dependency state changes, SWIR rejects the stale authorization and makes no unverified success claim.",
        "waiting": "Waiting for confirmation to update {package}.",
        "cancelled": "Update cancelled before authorization; no changes were made.",
        "authorizing": "Authorizing and updating {package}…",
        "committed": "Package update committed and verified. Transaction: {transaction}",
        "stopped": "Package update stopped ({code}): {message}",
    },
    "pl-PL": {
        "window_title": "Centrum aktualizacji SWIR",
        "brand": "◆  Centrum aktualizacji SWIR",
        "refresh": "Sprawdź ponownie lokalne metadane",
        "refresh_tooltip": "Przelicz podgląd aktualizacji na podstawie lokalnych metadanych pakietów",
        "calculating": "Obliczanie niedestrukcyjnego podglądu aktualizacji…",
        "explanation": "Lista korzysta wyłącznie z lokalnych metadanych pakietów. Każdy przycisk Aktualizuj żąda świeżego podglądu brokera SWIR; aplikacja nie odświeża repozytoriów ani nie wykonuje poleceń uprzywilejowanych.",
        "footer": "Aktualizacje pojedynczych pakietów używają ścieżki: podgląd → jawne potwierdzenie → Polkit → transakcja z dziennikiem. Aktualizacja zbiorcza i rollback pozostają niedostępne do osobnej weryfikacji.",
        "busy": "Transakcja pakietu jest już w toku.",
        "preview_unavailable": "Podgląd aktualizacji jest niedostępny: {message}",
        "broker_suffix": " • broker modyfikacji pakietów jest niedostępny",
        "truncated_suffix": " • pokazano pierwsze {limit}",
        "rows_status": "Aktualizacje pakietów w lokalnej symulacji: {count}{truncated}{broker}",
        "update": "Aktualizuj",
        "update_tooltip": "Wyświetl podgląd i potwierdź aktualizację tego pakietu przez SWIR",
        "broker_tooltip": "Broker transakcji pakietów SWIR jest niedostępny",
        "broker_unavailable": "Broker transakcji pakietów SWIR jest niedostępny; nie wprowadzono zmian.",
        "preparing": "Przygotowywanie zaufanego podglądu aktualizacji dla {package}…",
        "confirm_title": "Potwierdź aktualizację pakietu",
        "cancel": "Anuluj",
        "question": "Zaktualizować {package}?",
        "system_provider": "dostawca systemowy",
        "package_manager": "Menedżer pakietów: {manager}",
        "plan_digest": "Skrót planu: {digest}",
        "command_preview": "Podgląd polecenia brokera (tylko do wyświetlenia):\n{command}",
        "confirm_note": "Kontynuacja żąda autoryzacji Polkit i zatwierdza dokładnie ten podgląd. Jeśli stan zależności się zmieni, SWIR odrzuca nieaktualną autoryzację i nie zgłasza niezweryfikowanego sukcesu.",
        "waiting": "Oczekiwanie na potwierdzenie aktualizacji {package}.",
        "cancelled": "Aktualizację anulowano przed autoryzacją; nie wprowadzono zmian.",
        "authorizing": "Autoryzacja i aktualizacja {package}…",
        "committed": "Aktualizacja pakietu została zatwierdzona i zweryfikowana. Transakcja: {transaction}",
        "stopped": "Aktualizacja pakietu zatrzymana ({code}): {message}",
    },
    "nb-NO": {
        "window_title": "SWIR oppdateringssenter",
        "brand": "◆  SWIR oppdateringssenter",
        "refresh": "Sjekk lokale metadata på nytt",
        "refresh_tooltip": "Beregn oppdateringsoversikten på nytt fra lokale pakkemetadata",
        "calculating": "Beregner en ikke-destruktiv oppdateringsoversikt…",
        "explanation": "Listen bruker bare lokale pakkemetadata. Hver Oppdater-knapp ber SWIR-brokeren om en ny forhåndsvisning; appen oppdaterer ikke pakkekilder og kjører ingen privilegerte kommandoer.",
        "footer": "Oppdateringer per pakke bruker forhåndsvisning → eksplisitt bekreftelse → Polkit → journalført transaksjon. Masseoppdatering og tilbakeføring er utilgjengelig til de er verifisert separat.",
        "busy": "En pakketransaksjon pågår allerede.",
        "preview_unavailable": "Oppdateringsoversikten er utilgjengelig: {message}",
        "broker_suffix": " • brokeren for pakkeendringer er utilgjengelig",
        "truncated_suffix": " • viser de første {limit}",
        "rows_status": "{count} pakkeoppdateringer i den lokale simuleringen{truncated}{broker}",
        "update": "Oppdater",
        "update_tooltip": "Forhåndsvis og bekreft denne pakkeoppdateringen gjennom SWIR",
        "broker_tooltip": "SWIR-brokeren for pakketransaksjoner er ikke tilgjengelig",
        "broker_unavailable": "SWIR-brokeren for pakketransaksjoner er utilgjengelig; ingen endringer ble gjort.",
        "preparing": "Forbereder klarert oppdateringsoversikt for {package}…",
        "confirm_title": "Bekreft pakkeoppdatering",
        "cancel": "Avbryt",
        "question": "Oppdatere {package}?",
        "system_provider": "systemleverandør",
        "package_manager": "Pakkebehandler: {manager}",
        "plan_digest": "Plansammendrag: {digest}",
        "command_preview": "Forhåndsvisning av brokerkommando (kun visning):\n{command}",
        "confirm_note": "Fortsettelse ber om Polkit-autorisasjon og utfører nøyaktig denne forhåndsvisningen. Hvis avhengighetstilstanden endres, avviser SWIR den utdaterte autorisasjonen og hevder ikke ubekreftet suksess.",
        "waiting": "Venter på bekreftelse for å oppdatere {package}.",
        "cancelled": "Oppdateringen ble avbrutt før autorisasjon; ingen endringer ble gjort.",
        "authorizing": "Autoriserer og oppdaterer {package}…",
        "committed": "Pakkeoppdateringen er utført og verifisert. Transaksjon: {transaction}",
        "stopped": "Pakkeoppdateringen stoppet ({code}): {message}",
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


def run_self_test() -> int:
    english_keys = set(_TRANSLATIONS["en"])
    assert english_keys
    for language in ("pl-PL", "nb-NO"):
        assert set(_TRANSLATIONS[language]) == english_keys
    assert _locale_key("pl_PL.UTF-8") == "pl-PL"
    assert _locale_key("nb_NO.UTF-8") == "nb-NO"
    assert _locale_key("de-DE") == "en"
    assert tr("unsupported", "update") == "Update"
    assert tr("pl-PL", "update") == "Aktualizuj"
    assert tr("nb-NO", "cancel") == "Avbryt"
    print("SWIR Update Center locale self-test: OK")
    return 0


class SwirUpdateCenter(Gtk.Application):
    def __init__(self) -> None:
        super().__init__(application_id=APP_ID)
        self.locale, self.requested_language = resolve_locale()
        self.window: Gtk.ApplicationWindow | None = None
        self.listbox: Gtk.ListBox | None = None
        self.status_label: Gtk.Label | None = None
        self.generation = 0
        self.visible_rows = 0
        self.last_query_ok = False
        self.last_truncated = False
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
            raise RuntimeError("SWIR Update Center requires a graphical display")
        Gtk.StyleContext.add_provider_for_display(display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    def do_activate(self) -> None:
        if self.window is not None:
            self.window.present()
            return

        window = Gtk.ApplicationWindow(application=self)
        window.set_title(tr(self.locale, "window_title"))
        window.set_default_size(1000, 700)
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
        refresh = Gtk.Button(label=tr(self.locale, "refresh"))
        refresh.add_css_class("swir-button")
        refresh.set_tooltip_text(tr(self.locale, "refresh_tooltip"))
        refresh.connect("clicked", self._refresh_clicked)
        header.append(refresh)
        root.append(header)

        self.status_label = Gtk.Label(label=tr(self.locale, "calculating"), wrap=True)
        self.status_label.set_xalign(0)
        self.status_label.set_margin_start(12)
        self.status_label.set_margin_end(12)
        self.status_label.add_css_class("swir-status")
        root.append(self.status_label)

        explanation = Gtk.Label(label=tr(self.locale, "explanation"), wrap=True)
        explanation.add_css_class("swir-muted")
        explanation.set_xalign(0)
        explanation.set_margin_start(12)
        explanation.set_margin_end(12)
        root.append(explanation)

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
        self._refresh()

    def _clear_rows(self) -> None:
        assert self.listbox is not None
        child = self.listbox.get_first_child()
        while child is not None:
            next_child = child.get_next_sibling()
            self.listbox.remove(child)
            child = next_child

    def _refresh_clicked(self, _button: Gtk.Button) -> None:
        self._refresh()

    def _refresh(self) -> None:
        assert self.status_label is not None
        if self.mutation_busy:
            self.status_label.set_text(tr(self.locale, "busy"))
            return
        self.generation += 1
        generation = self.generation
        self.status_label.set_text(tr(self.locale, "calculating"))

        def run() -> None:
            try:
                snapshot = read_update_snapshot()
            except (OSError, ValueError) as exc:
                snapshot = UpdateSnapshot(rows=[], ok=False, truncated=False, message=str(exc))
            GLib.idle_add(self._finish_refresh, generation, snapshot)

        threading.Thread(target=run, name="swir-update-preview", daemon=True).start()

    def _finish_refresh(self, generation: int, snapshot: UpdateSnapshot) -> bool:
        if generation != self.generation:
            return False
        assert self.status_label is not None and self.listbox is not None
        self._clear_rows()
        self.last_query_ok = snapshot.ok
        self.last_truncated = snapshot.truncated
        self.visible_rows = len(snapshot.rows)
        broker_available = self.mutation_flow.available()

        if not snapshot.ok:
            self.status_label.set_text(tr(self.locale, "preview_unavailable", message=snapshot.message))
            return False

        if not snapshot.rows:
            suffix = "" if broker_available else tr(self.locale, "broker_suffix")
            self.status_label.set_text(f"{snapshot.message}{suffix}")
            return False

        suffix = tr(self.locale, "truncated_suffix", limit=MAX_UPDATE_ROWS) if snapshot.truncated else ""
        broker_suffix = "" if broker_available else tr(self.locale, "broker_suffix")
        self.status_label.set_text(
            tr(self.locale, "rows_status", count=len(snapshot.rows), truncated=suffix, broker=broker_suffix)
        )
        for update in snapshot.rows:
            row = Gtk.ListBoxRow()
            row.add_css_class("swir-row")
            outer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            box.set_hexpand(True)
            name = Gtk.Label(label=update.name)
            name.add_css_class("swir-name")
            name.set_xalign(0)
            name.set_selectable(True)
            box.append(name)
            versions = Gtk.Label(label=f"{update.current_version}  →  {update.candidate_version}", ellipsize=3)
            versions.add_css_class("swir-muted")
            versions.set_xalign(0)
            versions.set_tooltip_text(f"{update.current_version} → {update.candidate_version}")
            box.append(versions)
            outer.append(box)
            apply_button = Gtk.Button(label=tr(self.locale, "update"))
            apply_button.add_css_class("swir-primary")
            apply_button.set_sensitive(broker_available and not self.mutation_busy)
            apply_button.set_tooltip_text(
                tr(self.locale, "update_tooltip") if broker_available else tr(self.locale, "broker_tooltip")
            )
            apply_button.connect("clicked", self._update_clicked, update.name)
            outer.append(apply_button)
            row.set_child(outer)
            self.listbox.append(row)
        return False

    def _update_clicked(self, _button: Gtk.Button, package_name: str) -> None:
        assert self.status_label is not None
        if self.mutation_busy:
            self.status_label.set_text(tr(self.locale, "busy"))
            return
        if not self.mutation_flow.available():
            self.status_label.set_text(tr(self.locale, "broker_unavailable"))
            return
        self.mutation_busy = True
        self.last_transaction_state = "previewing"
        self.status_label.set_text(tr(self.locale, "preparing", package=package_name))

        def run() -> None:
            try:
                intent = self.mutation_flow.prepare("update", package_name)
                GLib.idle_add(self._show_confirmation, intent)
            except PackageBrokerError as exc:
                GLib.idle_add(self._mutation_failed, exc.code, str(exc))

        threading.Thread(target=run, name="swir-update-broker-preview", daemon=True).start()

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
        confirm = dialog.add_button(tr(self.locale, "update"), Gtk.ResponseType.OK)
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

        threading.Thread(target=run, name="swir-update-broker-commit", daemon=True).start()

    def _mutation_committed(self, transaction: dict) -> bool:
        assert self.status_label is not None
        self.mutation_busy = False
        self.last_transaction_state = str(transaction.get("state") or "committed")
        transaction_id = str(transaction.get("id") or "unknown")
        self.status_label.set_text(tr(self.locale, "committed", transaction=transaction_id))
        self._refresh()
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
            raise RuntimeError("refusing Update Center evidence path outside XDG_RUNTIME_DIR")
        status = tools_status()
        broker_available = self.mutation_flow.available()
        payload = {
            "schema": EVIDENCE_SCHEMA,
            "passed": status["aptGet"],
            "applicationId": APP_ID,
            "nativeToolkit": "gtk4",
            "displayProtocol": "wayland",
            "windowMapped": True,
            "privilegedOperationsInUi": False,
            "mutationFlowWired": True,
            "mutationControlsExposed": broker_available,
            "packageBrokerAvailable": broker_available,
            "explicitPlanConfirmationRequired": True,
            "repositoryRefreshPerformed": False,
            "packageTransactionBrokerBypassed": False,
            "directPackageToolMutation": False,
            "simulationOnlyForDiscovery": True,
            "bulkUpdateMutationExposed": False,
            "updateRowsBounded": MAX_UPDATE_ROWS,
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


if __name__ == "__main__":
    if "--self-test" in sys.argv[1:]:
        raise SystemExit(run_self_test())
    raise SystemExit(SwirUpdateCenter().run(sys.argv))
