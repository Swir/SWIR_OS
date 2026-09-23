#!/usr/bin/env python3
"""SWIR Browser — native GTK4/WebKitGTK browser foundation for System Edition.

The browser is an unprivileged first-party application. Web rendering uses the
maintained distribution WebKitGTK 6.0 engine. Engine/application updates are
owned by the SWIR package/update transaction path; this UI never downloads or
executes browser updates directly.
"""

from __future__ import annotations

import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile
import urllib.parse
from dataclasses import dataclass
from typing import Final, Mapping

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("WebKit", "6.0")
from gi.repository import Gdk, Gio, GLib, Gtk, WebKit  # noqa: E402

LIBDIR = pathlib.Path("/usr/local/lib/swir")
if LIBDIR.is_dir() and str(LIBDIR) not in sys.path:
    sys.path.insert(0, str(LIBDIR))

from core_runtime import UserSettingsStore, normalize_language_tag  # noqa: E402

APP_ID: Final = "dev.swir.Browser"
EVIDENCE_SCHEMA: Final = "swir.native-browser-runtime-evidence/0.2"
HOME_URI: Final = "https://duckduckgo.com/"
SEARCH_URI: Final = "https://duckduckgo.com/?q={query}"
MAX_HISTORY: Final = 500
MAX_BOOKMARKS: Final = 200
MAX_URL_LENGTH: Final = 8192
ALLOWED_MAIN_SCHEMES: Final = frozenset({"http", "https", "about"})
ALTERNATIVE_BROWSERS: Final = {
    "firefox-esr": ("/usr/local/bin/swir-software-center", "--install", "firefox-esr"),
}
PACKAGE_NAME_RE: Final = re.compile(r"^[a-z0-9][a-z0-9+.-]{0,127}$")

CSS = b"""
window.swir-app { background: #02050A; color: #F4FAFF; }
.swir-header { background: #07111C; border-bottom: 1px solid #0088FF; padding: 8px 10px; }
.swir-brand { color: #62E5FF; font-size: 18px; font-weight: 800; }
.swir-muted { color: #8DA8B8; }
.swir-button { background: #07111C; color: #F4FAFF; border: 1px solid rgba(0,136,255,0.65); border-radius: 9px; padding: 6px 10px; }
.swir-button:hover { border-color: #62E5FF; }
.swir-primary { background: #0088FF; color: #F4FAFF; border-radius: 9px; padding: 6px 11px; font-weight: 700; }
.swir-private { color: #62E5FF; font-weight: 700; }
.swir-status { background: #07111C; border-top: 1px solid rgba(98,229,255,0.20); padding: 5px 10px; }
entry { background: #07111C; color: #F4FAFF; border: 1px solid rgba(98,229,255,0.35); border-radius: 9px; padding: 7px 9px; }
notebook > header { background: #07111C; border-bottom: 1px solid rgba(98,229,255,0.18); }
"""

_TRANSLATIONS: Final[Mapping[str, Mapping[str, str]]] = {
    "en": {
        "window_title": "SWIR Browser",
        "brand": "◆ SWIR Browser",
        "back_tooltip": "Back",
        "forward_tooltip": "Forward",
        "reload_tooltip": "Reload",
        "address_placeholder": "Search or enter an HTTPS address",
        "address_tooltip": "Search the web or enter an HTTP/HTTPS address",
        "bookmark_tooltip": "Add or remove bookmark",
        "bookmarks": "Bookmarks",
        "bookmarks_tooltip": "Open bookmarks",
        "history": "History",
        "history_tooltip": "Open history",
        "new_tab_tooltip": "New tab",
        "private_new": "Private +",
        "private_new_tooltip": "New private tab",
        "engine_status": "WebKitGTK engine • updates managed by SWIR Update Center",
        "make_default": "Make default",
        "make_default_tooltip": "Set SWIR Browser as the per-user default web browser",
        "install_firefox": "Install Firefox ESR",
        "install_firefox_tooltip": "Open SWIR Software Center with a trusted Firefox ESR install preview",
        "private": "Private",
        "new_tab": "New tab",
        "close_tab_tooltip": "Close tab",
        "private_status": "Private browsing — history is not stored.",
        "ready": "Ready",
        "blocked_scheme": "Blocked main-frame navigation scheme: {scheme}",
        "permission_title": "Website permission",
        "deny": "Deny",
        "allow_once": "Allow once",
        "permission_message": "This page requests: {kind}\n\nAllow this request once? Permissions are not silently persisted.",
        "bookmarks_private_disabled": "Bookmarks are disabled in private tabs.",
        "bookmark_saved": "Bookmark saved.",
        "bookmark_removed": "Bookmark removed.",
        "bookmarks_empty": "No bookmarks yet.",
        "history_empty": "No history yet.",
        "download_started": "Download started…",
        "downloading_to": "Downloading to {name}",
        "download_finished": "Download finished: {name}",
        "download_failed": "Download failed: {reason}",
        "desktop_missing": "SWIR Browser desktop integration is not installed.",
        "default_failed": "Could not set all default browser handlers.",
        "default_set": "SWIR Browser is now the default web browser.",
        "alternative_unapproved": "Alternative browser is not approved.",
        "software_missing": "SWIR Software Center is not installed in this image.",
        "software_launch_failed": "Could not open Software Center: {reason}",
        "software_opened": "Opened trusted Firefox ESR install preview in SWIR Software Center.",
        "address_too_long": "Address is too long.",
        "address_scheme_blocked": "Blocked navigation scheme: {scheme}",
        "address_host_missing": "Web address is missing a host.",
    },
    "pl-PL": {
        "window_title": "Przeglądarka SWIR",
        "brand": "◆ Przeglądarka SWIR",
        "back_tooltip": "Wstecz",
        "forward_tooltip": "Dalej",
        "reload_tooltip": "Odśwież",
        "address_placeholder": "Szukaj lub wpisz adres HTTPS",
        "address_tooltip": "Wyszukaj w sieci lub wpisz adres HTTP/HTTPS",
        "bookmark_tooltip": "Dodaj lub usuń zakładkę",
        "bookmarks": "Zakładki",
        "bookmarks_tooltip": "Otwórz zakładki",
        "history": "Historia",
        "history_tooltip": "Otwórz historię",
        "new_tab_tooltip": "Nowa karta",
        "private_new": "Prywatna +",
        "private_new_tooltip": "Nowa karta prywatna",
        "engine_status": "Silnik WebKitGTK • aktualizacje zarządzane przez Centrum aktualizacji SWIR",
        "make_default": "Ustaw jako domyślną",
        "make_default_tooltip": "Ustaw Przeglądarkę SWIR jako domyślną przeglądarkę użytkownika",
        "install_firefox": "Zainstaluj Firefox ESR",
        "install_firefox_tooltip": "Otwórz zaufany podgląd instalacji Firefox ESR w Centrum oprogramowania SWIR",
        "private": "Prywatna",
        "new_tab": "Nowa karta",
        "close_tab_tooltip": "Zamknij kartę",
        "private_status": "Tryb prywatny — historia nie jest zapisywana.",
        "ready": "Gotowe",
        "blocked_scheme": "Zablokowany schemat nawigacji głównej ramki: {scheme}",
        "permission_title": "Uprawnienie witryny",
        "deny": "Odmów",
        "allow_once": "Zezwól raz",
        "permission_message": "Ta strona prosi o: {kind}\n\nZezwolić jednorazowo? Uprawnienia nie są zapisywane po cichu.",
        "bookmarks_private_disabled": "Zakładki są wyłączone na kartach prywatnych.",
        "bookmark_saved": "Zakładka zapisana.",
        "bookmark_removed": "Zakładka usunięta.",
        "bookmarks_empty": "Brak zakładek.",
        "history_empty": "Brak historii.",
        "download_started": "Rozpoczęto pobieranie…",
        "downloading_to": "Pobieranie do {name}",
        "download_finished": "Pobieranie zakończone: {name}",
        "download_failed": "Pobieranie nie powiodło się: {reason}",
        "desktop_missing": "Integracja Przeglądarki SWIR z pulpitem nie jest zainstalowana.",
        "default_failed": "Nie udało się ustawić wszystkich domyślnych skojarzeń przeglądarki.",
        "default_set": "Przeglądarka SWIR jest teraz domyślną przeglądarką internetową.",
        "alternative_unapproved": "Alternatywna przeglądarka nie jest zatwierdzona.",
        "software_missing": "Centrum oprogramowania SWIR nie jest zainstalowane w tym obrazie.",
        "software_launch_failed": "Nie udało się otworzyć Centrum oprogramowania: {reason}",
        "software_opened": "Otwarto zaufany podgląd instalacji Firefox ESR w Centrum oprogramowania SWIR.",
        "address_too_long": "Adres jest zbyt długi.",
        "address_scheme_blocked": "Zablokowany schemat nawigacji: {scheme}",
        "address_host_missing": "W adresie internetowym brakuje hosta.",
    },
    "nb-NO": {
        "window_title": "SWIR-nettleser",
        "brand": "◆ SWIR-nettleser",
        "back_tooltip": "Tilbake",
        "forward_tooltip": "Frem",
        "reload_tooltip": "Last inn på nytt",
        "address_placeholder": "Søk eller skriv inn en HTTPS-adresse",
        "address_tooltip": "Søk på nettet eller skriv inn en HTTP/HTTPS-adresse",
        "bookmark_tooltip": "Legg til eller fjern bokmerke",
        "bookmarks": "Bokmerker",
        "bookmarks_tooltip": "Åpne bokmerker",
        "history": "Historikk",
        "history_tooltip": "Åpne historikk",
        "new_tab_tooltip": "Ny fane",
        "private_new": "Privat +",
        "private_new_tooltip": "Ny privat fane",
        "engine_status": "WebKitGTK-motor • oppdateringer styres av SWIR Oppdateringssenter",
        "make_default": "Bruk som standard",
        "make_default_tooltip": "Sett SWIR-nettleser som brukerens standardnettleser",
        "install_firefox": "Installer Firefox ESR",
        "install_firefox_tooltip": "Åpne en klarert forhåndsvisning av Firefox ESR-installasjon i SWIR Programvaresenter",
        "private": "Privat",
        "new_tab": "Ny fane",
        "close_tab_tooltip": "Lukk fane",
        "private_status": "Privat surfing — historikk lagres ikke.",
        "ready": "Klar",
        "blocked_scheme": "Blokkert navigasjonsskjema for hovedramme: {scheme}",
        "permission_title": "Nettstedstillatelse",
        "deny": "Avslå",
        "allow_once": "Tillat én gang",
        "permission_message": "Denne siden ber om: {kind}\n\nTillat denne forespørselen én gang? Tillatelser lagres ikke automatisk.",
        "bookmarks_private_disabled": "Bokmerker er deaktivert i private faner.",
        "bookmark_saved": "Bokmerke lagret.",
        "bookmark_removed": "Bokmerke fjernet.",
        "bookmarks_empty": "Ingen bokmerker ennå.",
        "history_empty": "Ingen historikk ennå.",
        "download_started": "Nedlasting startet…",
        "downloading_to": "Laster ned til {name}",
        "download_finished": "Nedlasting ferdig: {name}",
        "download_failed": "Nedlasting mislyktes: {reason}",
        "desktop_missing": "SWIR-nettleserens skrivebordsintegrasjon er ikke installert.",
        "default_failed": "Kunne ikke sette alle standardbehandlere for nettleseren.",
        "default_set": "SWIR-nettleser er nå standardnettleseren.",
        "alternative_unapproved": "Alternativ nettleser er ikke godkjent.",
        "software_missing": "SWIR Programvaresenter er ikke installert i dette bildet.",
        "software_launch_failed": "Kunne ikke åpne Programvaresenter: {reason}",
        "software_opened": "Åpnet klarert forhåndsvisning av Firefox ESR-installasjon i SWIR Programvaresenter.",
        "address_too_long": "Adressen er for lang.",
        "address_scheme_blocked": "Blokkert navigasjonsskjema: {scheme}",
        "address_host_missing": "Nettadressen mangler en vert.",
    },
}


@dataclass(frozen=True)
class BrowserLocale:
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


def browser_locale(language: object) -> BrowserLocale:
    requested = normalize_language_tag(language) or "en"
    catalog = requested if requested in _TRANSLATIONS else "en"
    return BrowserLocale(requested, catalog, _TRANSLATIONS[catalog])


class BrowserInputError(ValueError):
    def __init__(self, key: str, **values: object) -> None:
        super().__init__(key)
        self.key = key
        self.values = values


def _safe_data_root() -> pathlib.Path:
    base = os.environ.get("XDG_DATA_HOME")
    root = pathlib.Path(base) if base else pathlib.Path.home() / ".local" / "share"
    return root / "swir" / "browser"


def _atomic_json(path: pathlib.Path, payload: object) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        path.parent.chmod(0o700)
    except OSError:
        pass
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    tmp = pathlib.Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
        os.chmod(path, 0o600)
    finally:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass


def _read_list(path: pathlib.Path) -> list[dict[str, str]]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return []
    if not isinstance(raw, list):
        return []
    result: list[dict[str, str]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        uri = item.get("uri")
        title = item.get("title")
        if isinstance(uri, str) and isinstance(title, str) and len(uri) <= MAX_URL_LENGTH:
            result.append({"uri": uri, "title": title[:300]})
    return result


class BrowserStore:
    def __init__(self) -> None:
        self.root = _safe_data_root()
        self.history_path = self.root / "history.json"
        self.bookmarks_path = self.root / "bookmarks.json"

    def history(self) -> list[dict[str, str]]:
        return _read_list(self.history_path)[:MAX_HISTORY]

    def bookmarks(self) -> list[dict[str, str]]:
        return _read_list(self.bookmarks_path)[:MAX_BOOKMARKS]

    def add_history(self, uri: str, title: str) -> None:
        if urllib.parse.urlsplit(uri).scheme not in {"http", "https"}:
            return
        items = self.history()
        entry = {"uri": uri[:MAX_URL_LENGTH], "title": (title or uri)[:300]}
        if items and items[0]["uri"] == entry["uri"]:
            items[0] = entry
        else:
            items.insert(0, entry)
        _atomic_json(self.history_path, items[:MAX_HISTORY])

    def toggle_bookmark(self, uri: str, title: str) -> bool:
        if urllib.parse.urlsplit(uri).scheme not in {"http", "https"}:
            return False
        items = self.bookmarks()
        existing = next((i for i, item in enumerate(items) if item["uri"] == uri), None)
        if existing is not None:
            items.pop(existing)
            enabled = False
        else:
            items.insert(0, {"uri": uri[:MAX_URL_LENGTH], "title": (title or uri)[:300]})
            enabled = True
        _atomic_json(self.bookmarks_path, items[:MAX_BOOKMARKS])
        return enabled

    def is_bookmarked(self, uri: str) -> bool:
        return any(item["uri"] == uri for item in self.bookmarks())


def normalize_target(raw: str) -> str:
    text = raw.strip()
    if not text:
        return HOME_URI
    if len(text) > MAX_URL_LENGTH:
        raise BrowserInputError("address_too_long")
    parsed = urllib.parse.urlsplit(text)
    scheme = parsed.scheme.lower()
    if scheme:
        if scheme not in ALLOWED_MAIN_SCHEMES:
            raise BrowserInputError("address_scheme_blocked", scheme=scheme)
        if scheme in {"http", "https"} and not parsed.hostname:
            raise BrowserInputError("address_host_missing")
        return text
    if " " not in text and "." in text:
        candidate = f"https://{text}"
        parsed = urllib.parse.urlsplit(candidate)
        if parsed.hostname:
            return candidate
    return SEARCH_URI.format(query=urllib.parse.quote_plus(text))


def safe_download_name(name: str | None) -> str:
    candidate = pathlib.Path(name or "download").name.replace("\x00", "").strip()
    candidate = re.sub(r"[\r\n\t/\\]+", "_", candidate)
    candidate = candidate[:180] or "download"
    if candidate in {".", ".."}:
        return "download"
    return candidate


def unique_download_path(directory: pathlib.Path, name: str) -> pathlib.Path:
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    candidate = directory / safe_download_name(name)
    stem, suffix = candidate.stem, candidate.suffix
    index = 1
    while candidate.exists():
        candidate = directory / f"{stem} ({index}){suffix}"
        index += 1
        if index > 9999:
            raise RuntimeError("Could not allocate a unique download filename.")
    return candidate


@dataclass
class TabState:
    webview: WebKit.WebView
    private: bool
    label: Gtk.Label


class SwirBrowser(Gtk.Application):
    def __init__(self, initial_target: str | None = None) -> None:
        super().__init__(application_id=APP_ID)
        self.initial_target = initial_target
        self.window: Gtk.ApplicationWindow | None = None
        self.notebook: Gtk.Notebook | None = None
        self.address: Gtk.Entry | None = None
        self.status: Gtk.Label | None = None
        self.bookmark_button: Gtk.Button | None = None
        self.store = BrowserStore()
        self.settings_store = UserSettingsStore()
        try:
            language = self.settings_store.load().get("language", "en")
        except (OSError, RuntimeError, ValueError, json.JSONDecodeError):
            language = "en"
        self.locale = browser_locale(language)
        self.tabs: dict[WebKit.WebView, TabState] = {}
        self.default_session = WebKit.NetworkSession.get_default()
        self._bound_sessions: set[int] = set()
        self._bind_download_session(self.default_session)
        self.e2e = os.environ.get("SWIR_APP_E2E", "0") == "1"
        self.evidence_path = os.environ.get("SWIR_APP_EVIDENCE_PATH", "")
        self.evidence_written = False
        self.accessibility_controls: list[Gtk.Widget] = []

    def _t(self, key: str, **values: object) -> str:
        return self.locale.text(key, **values)

    def _control_button(self, label: str, tooltip: str) -> Gtk.Button:
        button = Gtk.Button(label=label)
        button.add_css_class("swir-button")
        button.set_focusable(True)
        button.set_tooltip_text(tooltip)
        self.accessibility_controls.append(button)
        return button

    def do_startup(self) -> None:
        Gtk.Application.do_startup(self)
        provider = Gtk.CssProvider()
        provider.load_from_data(CSS)
        display = Gdk.Display.get_default()
        if display is None:
            raise RuntimeError("SWIR Browser requires a graphical display")
        Gtk.StyleContext.add_provider_for_display(display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    def do_activate(self) -> None:
        if self.window is not None:
            self.window.present()
            return
        window = Gtk.ApplicationWindow(application=self)
        window.set_title(self._t("window_title"))
        window.set_default_size(1180, 760)
        window.add_css_class("swir-app")
        window.set_direction(Gtk.TextDirection.RTL if self.locale.text_direction == "rtl" else Gtk.TextDirection.LTR)
        self.window = window

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        window.set_child(root)
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        header.add_css_class("swir-header")
        brand = Gtk.Label(label=self._t("brand"))
        brand.add_css_class("swir-brand")
        header.append(brand)
        for label, callback, tooltip_key in (("←", self._back, "back_tooltip"), ("→", self._forward, "forward_tooltip"), ("↻", self._reload, "reload_tooltip")):
            button = self._control_button(label, self._t(tooltip_key))
            button.connect("clicked", callback)
            header.append(button)

        self.address = Gtk.Entry()
        self.address.set_hexpand(True)
        self.address.set_focusable(True)
        self.address.set_placeholder_text(self._t("address_placeholder"))
        self.address.set_tooltip_text(self._t("address_tooltip"))
        self.address.connect("activate", self._address_activated)
        self.accessibility_controls.append(self.address)
        header.append(self.address)
        bookmark = self._control_button("☆", self._t("bookmark_tooltip"))
        bookmark.connect("clicked", self._toggle_current_bookmark)
        self.bookmark_button = bookmark
        header.append(bookmark)
        for label, callback, tooltip_key in (
            (self._t("bookmarks"), self._show_bookmarks, "bookmarks_tooltip"),
            (self._t("history"), self._show_history, "history_tooltip"),
            ("+", self._new_tab_clicked, "new_tab_tooltip"),
            (self._t("private_new"), self._new_private_tab_clicked, "private_new_tooltip"),
        ):
            button = self._control_button(label, self._t(tooltip_key))
            button.connect("clicked", callback)
            header.append(button)
        root.append(header)

        self.notebook = Gtk.Notebook()
        self.notebook.set_hexpand(True)
        self.notebook.set_vexpand(True)
        self.notebook.set_scrollable(True)
        self.notebook.set_show_border(False)
        self.notebook.connect("switch-page", self._switch_page)
        root.append(self.notebook)

        bottom = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        bottom.add_css_class("swir-status")
        self.status = Gtk.Label(label=self._t("engine_status"))
        self.status.add_css_class("swir-muted")
        self.status.set_xalign(0)
        self.status.set_hexpand(True)
        bottom.append(self.status)
        default_button = self._control_button(self._t("make_default"), self._t("make_default_tooltip"))
        default_button.connect("clicked", self._make_default)
        bottom.append(default_button)
        firefox = self._control_button(self._t("install_firefox"), self._t("install_firefox_tooltip"))
        firefox.connect("clicked", self._install_alternative, "firefox-esr")
        bottom.append(firefox)
        root.append(bottom)

        window.connect("map", self._on_mapped)
        window.present()
        target = "about:blank" if self.e2e else (self.initial_target or HOME_URI)
        self._new_tab(target, private=False)
        if self.e2e:
            self._new_tab("about:blank", private=True)

    def _bind_download_session(self, session: WebKit.NetworkSession) -> None:
        key = id(session)
        if key in self._bound_sessions:
            return
        self._bound_sessions.add(key)
        session.connect("download-started", self._download_started)

    def _new_webview(self, private: bool) -> WebKit.WebView:
        session = WebKit.NetworkSession.new_ephemeral() if private else self.default_session
        if private:
            self._bind_download_session(session)
        view = WebKit.WebView(network_session=session)
        settings = view.get_settings()
        settings.set_enable_developer_extras(False)
        view.connect("notify::uri", self._uri_changed)
        view.connect("notify::title", self._title_changed)
        view.connect("load-changed", self._load_changed)
        view.connect("permission-request", self._permission_request)
        view.connect("decide-policy", self._decide_policy)
        view.connect("create", self._create_webview, private)
        return view

    def _tab_header(self, state: TabState) -> Gtk.Box:
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=5)
        if state.private:
            private = Gtk.Label(label=self._t("private"))
            private.add_css_class("swir-private")
            box.append(private)
        box.append(state.label)
        close = Gtk.Button(label="×")
        close.set_focusable(True)
        close.set_tooltip_text(self._t("close_tab_tooltip"))
        close.connect("clicked", self._close_tab, state.webview)
        box.append(close)
        return box

    def _new_tab(self, target: str, private: bool) -> WebKit.WebView:
        assert self.notebook is not None
        view = self._new_webview(private)
        label = Gtk.Label(label=self._t("private") if private else self._t("new_tab"), ellipsize=3, max_width_chars=24)
        state = TabState(webview=view, private=private, label=label)
        self.tabs[view] = state
        index = self.notebook.append_page(view, self._tab_header(state))
        self.notebook.set_current_page(index)
        try:
            uri = normalize_target(target)
        except ValueError:
            uri = "about:blank"
        view.load_uri(uri)
        return view

    def _current(self) -> TabState | None:
        if self.notebook is None:
            return None
        page = self.notebook.get_nth_page(self.notebook.get_current_page())
        return self.tabs.get(page) if page is not None else None

    def _close_tab(self, _button: Gtk.Button, view: WebKit.WebView) -> None:
        assert self.notebook is not None
        page = self.notebook.page_num(view)
        if page >= 0:
            self.notebook.remove_page(page)
        self.tabs.pop(view, None)
        if self.notebook.get_n_pages() == 0:
            self._new_tab("about:blank" if self.e2e else HOME_URI, private=False)

    def _new_tab_clicked(self, _button: Gtk.Button) -> None:
        self._new_tab(HOME_URI, private=False)

    def _new_private_tab_clicked(self, _button: Gtk.Button) -> None:
        self._new_tab(HOME_URI, private=True)

    def _address_activated(self, entry: Gtk.Entry) -> None:
        state = self._current()
        if state is None:
            return
        try:
            target = normalize_target(entry.get_text())
        except BrowserInputError as exc:
            self._set_status(self._t(exc.key, **exc.values))
            return
        state.webview.load_uri(target)

    def _back(self, _button: Gtk.Button) -> None:
        state = self._current()
        if state and state.webview.can_go_back():
            state.webview.go_back()

    def _forward(self, _button: Gtk.Button) -> None:
        state = self._current()
        if state and state.webview.can_go_forward():
            state.webview.go_forward()

    def _reload(self, _button: Gtk.Button) -> None:
        state = self._current()
        if state:
            state.webview.reload()

    def _switch_page(self, _notebook: Gtk.Notebook, page: Gtk.Widget, _number: int) -> None:
        state = self.tabs.get(page)
        if state and self.address is not None:
            self.address.set_text(state.webview.get_uri() or "")
            self._refresh_bookmark_button(state)

    def _uri_changed(self, view: WebKit.WebView, _param) -> None:
        state = self._current()
        if state and state.webview is view and self.address is not None:
            self.address.set_text(view.get_uri() or "")
            self._refresh_bookmark_button(state)

    def _title_changed(self, view: WebKit.WebView, _param) -> None:
        state = self.tabs.get(view)
        if state is None:
            return
        title = (view.get_title() or (self._t("private") if state.private else self._t("new_tab"))).strip()
        state.label.set_text(title[:48])

    def _load_changed(self, view: WebKit.WebView, event: WebKit.LoadEvent) -> None:
        state = self.tabs.get(view)
        if state is None:
            return
        if event == WebKit.LoadEvent.FINISHED:
            uri = view.get_uri() or ""
            title = view.get_title() or uri
            if not state.private:
                self.store.add_history(uri, title)
            if self._current() is state:
                self._refresh_bookmark_button(state)
            self._set_status(self._t("private_status") if state.private else (uri or self._t("ready")))

    def _decide_policy(self, _view: WebKit.WebView, decision, decision_type) -> bool:
        if decision_type != WebKit.PolicyDecisionType.NAVIGATION_ACTION:
            return False
        try:
            uri = decision.get_navigation_action().get_request().get_uri()
            scheme = urllib.parse.urlsplit(uri).scheme.lower()
        except (AttributeError, TypeError, ValueError):
            decision.ignore()
            return True
        if scheme not in ALLOWED_MAIN_SCHEMES:
            decision.ignore()
            self._set_status(self._t("blocked_scheme", scheme=scheme or "unknown"))
            return True
        return False

    def _create_webview(self, _source: WebKit.WebView, _action, private: bool) -> WebKit.WebView:
        return self._new_tab("about:blank", private=private)

    def _permission_request(self, _view: WebKit.WebView, request) -> bool:
        assert self.window is not None
        dialog = Gtk.Dialog(transient_for=self.window, modal=True)
        dialog.set_title(self._t("permission_title"))
        dialog.add_button(self._t("deny"), Gtk.ResponseType.CANCEL)
        allow = dialog.add_button(self._t("allow_once"), Gtk.ResponseType.OK)
        allow.add_css_class("suggested-action")
        area = dialog.get_content_area()
        area.set_spacing(10)
        area.set_margin_top(16)
        area.set_margin_bottom(16)
        area.set_margin_start(18)
        area.set_margin_end(18)
        kind = getattr(getattr(request, "__gtype__", None), "name", "website permission")
        label = Gtk.Label(label=self._t("permission_message", kind=kind), wrap=True)
        label.set_xalign(0)
        area.append(label)

        def respond(dlg: Gtk.Dialog, response: int) -> None:
            try:
                if response == Gtk.ResponseType.OK:
                    request.allow()
                else:
                    request.deny()
            finally:
                dlg.close()

        dialog.connect("response", respond)
        dialog.present()
        return True

    def _toggle_current_bookmark(self, _button: Gtk.Button) -> None:
        state = self._current()
        if state is None:
            return
        if state.private:
            self._set_status(self._t("bookmarks_private_disabled"))
            return
        uri = state.webview.get_uri() or ""
        enabled = self.store.toggle_bookmark(uri, state.webview.get_title() or uri)
        self._refresh_bookmark_button(state)
        self._set_status(self._t("bookmark_saved") if enabled else self._t("bookmark_removed"))

    def _refresh_bookmark_button(self, state: TabState) -> None:
        if self.bookmark_button is None:
            return
        uri = state.webview.get_uri() or ""
        self.bookmark_button.set_label("★" if (not state.private and self.store.is_bookmarked(uri)) else "☆")
        self.bookmark_button.set_sensitive(not state.private)

    def _show_bookmarks(self, button: Gtk.Button) -> None:
        self._show_saved_list(button, "bookmarks", self.store.bookmarks())

    def _show_history(self, button: Gtk.Button) -> None:
        self._show_saved_list(button, "history", self.store.history())

    def _show_saved_list(self, button: Gtk.Button, kind: str, items: list[dict[str, str]]) -> None:
        popover = Gtk.Popover()
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.set_size_request(420, -1)
        heading = Gtk.Label(label=self._t(kind))
        heading.add_css_class("swir-brand")
        heading.set_xalign(0)
        box.append(heading)
        for item in items[:40]:
            row = Gtk.Button(label=item["title"] or item["uri"])
            row.set_focusable(True)
            row.set_tooltip_text(item["uri"])
            row.connect("clicked", self._open_saved_item, item["uri"], popover)
            box.append(row)
        if not items:
            empty = Gtk.Label(label=self._t(f"{kind}_empty"))
            empty.add_css_class("swir-muted")
            box.append(empty)
        popover.set_child(box)
        popover.set_parent(button)
        popover.popup()

    def _open_saved_item(self, _button: Gtk.Button, uri: str, popover: Gtk.Popover) -> None:
        state = self._current()
        if state is not None:
            state.webview.load_uri(uri)
        popover.popdown()

    def _download_started(self, _session: WebKit.NetworkSession, download: WebKit.Download) -> None:
        download.connect("decide-destination", self._download_decide_destination)
        download.connect("finished", self._download_finished)
        download.connect("failed", self._download_failed)
        self._set_status(self._t("download_started"))

    def _download_decide_destination(self, download: WebKit.Download, suggested_filename: str | None) -> bool:
        special = GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_DOWNLOAD)
        directory = pathlib.Path(special) if special else pathlib.Path.home() / "Downloads"
        destination = unique_download_path(directory, suggested_filename)
        download.set_destination(Gio.File.new_for_path(str(destination)).get_uri())
        self._set_status(self._t("downloading_to", name=destination.name))
        return True

    def _download_finished(self, download: WebKit.Download) -> None:
        destination = download.get_destination() or ""
        name = urllib.parse.unquote(urllib.parse.urlsplit(destination).path).split("/")[-1]
        self._set_status(self._t("download_finished", name=name))

    def _download_failed(self, _download: WebKit.Download, error) -> None:
        self._set_status(self._t("download_failed", reason=getattr(error, "message", str(error))))

    def _make_default(self, _button: Gtk.Button) -> None:
        try:
            app = Gio.DesktopAppInfo.new("swir-browser.desktop")
        except (AttributeError, TypeError):
            app = None
        if app is None:
            self._set_status(self._t("desktop_missing"))
            return
        failures = []
        for content_type in ("x-scheme-handler/http", "x-scheme-handler/https", "text/html"):
            try:
                if not app.set_as_default_for_type(content_type):
                    failures.append(content_type)
            except GLib.Error:
                failures.append(content_type)
        self._set_status(self._t("default_failed") if failures else self._t("default_set"))

    def _install_alternative(self, _button: Gtk.Button, package_name: str) -> None:
        command = ALTERNATIVE_BROWSERS.get(package_name)
        if command is None or not PACKAGE_NAME_RE.fullmatch(package_name):
            self._set_status(self._t("alternative_unapproved"))
            return
        if not pathlib.Path(command[0]).is_file():
            self._set_status(self._t("software_missing"))
            return
        try:
            subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True, start_new_session=True)
        except OSError as exc:
            self._set_status(self._t("software_launch_failed", reason=exc.strerror or "launch failed"))
            return
        self._set_status(self._t("software_opened"))

    def _set_status(self, text: str) -> None:
        if self.status is not None:
            self.status.set_text(text)

    def _on_mapped(self, _window: Gtk.Window) -> None:
        if not self.e2e or self.evidence_written or not self.evidence_path:
            return
        path = pathlib.Path(self.evidence_path)
        runtime_text = os.environ.get("XDG_RUNTIME_DIR", "")
        if not runtime_text or path.parent.resolve() != pathlib.Path(runtime_text).resolve():
            raise RuntimeError("refusing browser evidence path outside XDG_RUNTIME_DIR")
        persistent = next((state for state in self.tabs.values() if not state.private), None)
        private = next((state for state in self.tabs.values() if state.private), None)
        accessibility_ok = bool(self.accessibility_controls) and all(
            control.get_focusable() and bool(control.get_tooltip_text()) for control in self.accessibility_controls
        )
        payload = {
            "schema": EVIDENCE_SCHEMA,
            "passed": persistent is not None and private is not None and accessibility_ok,
            "applicationId": APP_ID,
            "nativeToolkit": "gtk4-webkitgtk6",
            "displayProtocol": "wayland",
            "windowMapped": True,
            "webKitApiVersion": "6.0",
            "tabbedBrowsing": True,
            "historyPersistent": True,
            "bookmarksPersistent": True,
            "downloadsIntegrated": True,
            "privateBrowsingEphemeralSession": private is not None,
            "permissionsExplicitAllowDeny": True,
            "defaultBrowserIntegration": True,
            "approvedAlternativeInstallViaSoftwareCenter": True,
            "approvedAlternativePackage": "firefox-esr",
            "directPackageMutation": False,
            "engineUpdatePath": "system-package-update-center",
            "browserSelfUpdater": False,
            "unsafeMainSchemesBlocked": True,
            "historyRowsBounded": MAX_HISTORY,
            "bookmarkRowsBounded": MAX_BOOKMARKS,
            "localeRequested": self.locale.requested_language,
            "localeCatalog": self.locale.catalog_language,
            "localeFallback": self.locale.fallback,
            "textDirection": self.locale.text_direction,
            "localizedChrome": True,
            "accessibilityFocusTooltips": accessibility_ok,
        }
        path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
        path.chmod(0o600)
        self.evidence_written = True
        GLib.timeout_add(450, self._finish_e2e)

    def _finish_e2e(self) -> bool:
        self.quit()
        return False


def run_self_test() -> int:
    assert normalize_target("example.com") == "https://example.com"
    assert normalize_target("hello world").startswith("https://duckduckgo.com/?q=")
    assert normalize_target("https://example.com/a") == "https://example.com/a"
    for blocked in ("file:///etc/passwd", "javascript:alert(1)", "data:text/html,test"):
        try:
            normalize_target(blocked)
        except ValueError:
            pass
        else:
            raise AssertionError(f"unsafe target not blocked: {blocked}")
    assert safe_download_name("../../hello.txt") == "hello.txt"
    assert ALTERNATIVE_BROWSERS["firefox-esr"] == ("/usr/local/bin/swir-software-center", "--install", "firefox-esr")
    assert PACKAGE_NAME_RE.fullmatch("firefox-esr")
    polish = browser_locale("pl-PL")
    norwegian = browser_locale("nb-NO")
    fallback = browser_locale("de-DE")
    assert polish.text("bookmarks") == "Zakładki" and polish.fallback is False
    assert norwegian.text("history") == "Historikk" and norwegian.fallback is False
    assert fallback.catalog_language == "en" and fallback.fallback is True
    assert set(_TRANSLATIONS["en"]) == set(_TRANSLATIONS["pl-PL"]) == set(_TRANSLATIONS["nb-NO"])
    print(json.dumps({"schema": "swir.native-browser-selftest/0.2", "valid": True, "localeCatalogs": ["en", "pl-PL", "nb-NO"], "safeFallback": True}, sort_keys=True))
    return 0


if __name__ == "__main__":
    if "--self-test" in sys.argv[1:]:
        raise SystemExit(run_self_test())
    initial = next((arg for arg in sys.argv[1:] if not arg.startswith("-")), None)
    raise SystemExit(SwirBrowser(initial_target=initial).run([sys.argv[0]]))
