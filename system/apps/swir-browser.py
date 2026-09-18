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
from typing import Final

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("WebKit", "6.0")
from gi.repository import Gdk, Gio, GLib, Gtk, WebKit  # noqa: E402

APP_ID: Final = "dev.swir.Browser"
EVIDENCE_SCHEMA: Final = "swir.native-browser-runtime-evidence/0.1"
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
        raise ValueError("Address is too long.")
    parsed = urllib.parse.urlsplit(text)
    scheme = parsed.scheme.lower()
    if scheme:
        if scheme not in ALLOWED_MAIN_SCHEMES:
            raise ValueError(f"Blocked navigation scheme: {scheme}")
        if scheme in {"http", "https"} and not parsed.hostname:
            raise ValueError("Web address is missing a host.")
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
        self.tabs: dict[WebKit.WebView, TabState] = {}
        self.default_session = WebKit.NetworkSession.get_default()
        self._bound_sessions: set[int] = set()
        self._bind_download_session(self.default_session)
        self.e2e = os.environ.get("SWIR_APP_E2E", "0") == "1"
        self.evidence_path = os.environ.get("SWIR_APP_EVIDENCE_PATH", "")
        self.evidence_written = False

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
        window.set_title("SWIR Browser")
        window.set_default_size(1180, 760)
        window.add_css_class("swir-app")
        self.window = window

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        window.set_child(root)
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        header.add_css_class("swir-header")
        brand = Gtk.Label(label="◆ SWIR Browser")
        brand.add_css_class("swir-brand")
        header.append(brand)
        for label, callback, tooltip in (("←", self._back, "Back"), ("→", self._forward, "Forward"), ("↻", self._reload, "Reload")):
            button = Gtk.Button(label=label)
            button.add_css_class("swir-button")
            button.set_tooltip_text(tooltip)
            button.connect("clicked", callback)
            header.append(button)

        self.address = Gtk.Entry()
        self.address.set_hexpand(True)
        self.address.set_placeholder_text("Search or enter an HTTPS address")
        self.address.connect("activate", self._address_activated)
        header.append(self.address)
        bookmark = Gtk.Button(label="☆")
        bookmark.add_css_class("swir-button")
        bookmark.set_tooltip_text("Add/remove bookmark")
        bookmark.connect("clicked", self._toggle_current_bookmark)
        self.bookmark_button = bookmark
        header.append(bookmark)
        for label, callback, tooltip in (
            ("Bookmarks", self._show_bookmarks, "Open bookmarks"),
            ("History", self._show_history, "Open history"),
            ("+", self._new_tab_clicked, "New tab"),
            ("Private +", self._new_private_tab_clicked, "New private tab"),
        ):
            button = Gtk.Button(label=label)
            button.add_css_class("swir-button")
            button.set_tooltip_text(tooltip)
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
        self.status = Gtk.Label(label="WebKitGTK engine • updates managed by SWIR Update Center")
        self.status.add_css_class("swir-muted")
        self.status.set_xalign(0)
        self.status.set_hexpand(True)
        bottom.append(self.status)
        default_button = Gtk.Button(label="Make default")
        default_button.add_css_class("swir-button")
        default_button.connect("clicked", self._make_default)
        bottom.append(default_button)
        firefox = Gtk.Button(label="Install Firefox ESR")
        firefox.add_css_class("swir-button")
        firefox.set_tooltip_text("Open SWIR Software Center with a trusted Firefox ESR install preview")
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
            private = Gtk.Label(label="Private")
            private.add_css_class("swir-private")
            box.append(private)
        box.append(state.label)
        close = Gtk.Button(label="×")
        close.set_tooltip_text("Close tab")
        close.connect("clicked", self._close_tab, state.webview)
        box.append(close)
        return box

    def _new_tab(self, target: str, private: bool) -> WebKit.WebView:
        assert self.notebook is not None
        view = self._new_webview(private)
        label = Gtk.Label(label="Private" if private else "New tab", ellipsize=3, max_width_chars=24)
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
        except ValueError as exc:
            self._set_status(str(exc))
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
        title = (view.get_title() or ("Private" if state.private else "New tab")).strip()
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
            self._set_status("Private browsing — history is not stored." if state.private else (uri or "Ready"))

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
            self._set_status(f"Blocked main-frame navigation scheme: {scheme or 'unknown'}")
            return True
        return False

    def _create_webview(self, _source: WebKit.WebView, _action, private: bool) -> WebKit.WebView:
        return self._new_tab("about:blank", private=private)

    def _permission_request(self, _view: WebKit.WebView, request) -> bool:
        assert self.window is not None
        dialog = Gtk.Dialog(transient_for=self.window, modal=True)
        dialog.set_title("Website permission")
        dialog.add_button("Deny", Gtk.ResponseType.CANCEL)
        allow = dialog.add_button("Allow once", Gtk.ResponseType.OK)
        allow.add_css_class("suggested-action")
        area = dialog.get_content_area()
        area.set_spacing(10)
        area.set_margin_top(16)
        area.set_margin_bottom(16)
        area.set_margin_start(18)
        area.set_margin_end(18)
        kind = getattr(getattr(request, "__gtype__", None), "name", "website permission")
        label = Gtk.Label(label=f"This page requests: {kind}\n\nAllow this request once? Permissions are not silently persisted.", wrap=True)
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
            self._set_status("Bookmarks are disabled in private tabs.")
            return
        uri = state.webview.get_uri() or ""
        enabled = self.store.toggle_bookmark(uri, state.webview.get_title() or uri)
        self._refresh_bookmark_button(state)
        self._set_status("Bookmark saved." if enabled else "Bookmark removed.")

    def _refresh_bookmark_button(self, state: TabState) -> None:
        if self.bookmark_button is None:
            return
        uri = state.webview.get_uri() or ""
        self.bookmark_button.set_label("★" if (not state.private and self.store.is_bookmarked(uri)) else "☆")
        self.bookmark_button.set_sensitive(not state.private)

    def _show_bookmarks(self, button: Gtk.Button) -> None:
        self._show_saved_list(button, "Bookmarks", self.store.bookmarks())

    def _show_history(self, button: Gtk.Button) -> None:
        self._show_saved_list(button, "History", self.store.history())

    def _show_saved_list(self, button: Gtk.Button, title: str, items: list[dict[str, str]]) -> None:
        popover = Gtk.Popover()
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.set_size_request(420, -1)
        heading = Gtk.Label(label=title)
        heading.add_css_class("swir-brand")
        heading.set_xalign(0)
        box.append(heading)
        for item in items[:40]:
            row = Gtk.Button(label=item["title"] or item["uri"])
            row.set_tooltip_text(item["uri"])
            row.connect("clicked", self._open_saved_item, item["uri"], popover)
            box.append(row)
        if not items:
            empty = Gtk.Label(label=f"No {title.lower()} yet.")
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
        self._set_status("Download started…")

    def _download_decide_destination(self, download: WebKit.Download, suggested_filename: str | None) -> bool:
        special = GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_DOWNLOAD)
        directory = pathlib.Path(special) if special else pathlib.Path.home() / "Downloads"
        destination = unique_download_path(directory, suggested_filename)
        download.set_destination(Gio.File.new_for_path(str(destination)).get_uri())
        self._set_status(f"Downloading to {destination.name}")
        return True

    def _download_finished(self, download: WebKit.Download) -> None:
        destination = download.get_destination() or ""
        self._set_status(f"Download finished: {urllib.parse.unquote(urllib.parse.urlsplit(destination).path).split('/')[-1]}")

    def _download_failed(self, _download: WebKit.Download, error) -> None:
        self._set_status(f"Download failed: {getattr(error, 'message', str(error))}")

    def _make_default(self, _button: Gtk.Button) -> None:
        try:
            app = Gio.DesktopAppInfo.new("swir-browser.desktop")
        except (AttributeError, TypeError):
            app = None
        if app is None:
            self._set_status("SWIR Browser desktop integration is not installed.")
            return
        failures = []
        for content_type in ("x-scheme-handler/http", "x-scheme-handler/https", "text/html"):
            try:
                if not app.set_as_default_for_type(content_type):
                    failures.append(content_type)
            except GLib.Error:
                failures.append(content_type)
        self._set_status("Could not set all default browser handlers." if failures else "SWIR Browser is now the default web browser.")

    def _install_alternative(self, _button: Gtk.Button, package_name: str) -> None:
        command = ALTERNATIVE_BROWSERS.get(package_name)
        if command is None or not PACKAGE_NAME_RE.fullmatch(package_name):
            self._set_status("Alternative browser is not approved.")
            return
        if not pathlib.Path(command[0]).is_file():
            self._set_status("SWIR Software Center is not installed in this image.")
            return
        try:
            subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True, start_new_session=True)
        except OSError as exc:
            self._set_status(f"Could not open Software Center: {exc.strerror or 'launch failed'}")
            return
        self._set_status("Opened trusted Firefox ESR install preview in SWIR Software Center.")

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
        payload = {
            "schema": EVIDENCE_SCHEMA,
            "passed": persistent is not None and private is not None,
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
    print(json.dumps({"schema": "swir.native-browser-selftest/0.1", "valid": True}, sort_keys=True))
    return 0


if __name__ == "__main__":
    if "--self-test" in sys.argv[1:]:
        raise SystemExit(run_self_test())
    initial = next((arg for arg in sys.argv[1:] if not arg.startswith("-")), None)
    raise SystemExit(SwirBrowser(initial_target=initial).run([sys.argv[0]]))
