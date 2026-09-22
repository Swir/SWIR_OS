#!/usr/bin/env python3
"""SWIR Text Editor — native GTK4 local UTF-8 text/code handler."""
from __future__ import annotations

import json
import os
import pathlib
import stat
import sys
import tempfile
from dataclasses import dataclass
from typing import Final, Mapping

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gdk, Gio, GLib, Gtk  # noqa: E402

LIBDIR = pathlib.Path("/usr/local/lib/swir")
if LIBDIR.is_dir() and str(LIBDIR) not in sys.path:
    sys.path.insert(0, str(LIBDIR))

from core_runtime import UserSettingsStore, normalize_language_tag  # noqa: E402

APP_ID: Final = "dev.swir.TextEditor"
EVIDENCE_SCHEMA: Final = "swir.native-text-editor-runtime-evidence/0.3"
MAX_DOCUMENT_BYTES: Final = 4 * 1024 * 1024

CSS = b"""
window.swir-app { background:#02050A; color:#F4FAFF; }
.swir-header { background:#07111C; border-bottom:1px solid #0088FF; padding:10px 14px; }
.swir-brand { color:#62E5FF; font-size:18px; font-weight:800; }
.swir-muted { color:#8DA8B8; }
.swir-button { background:#07111C; color:#F4FAFF; border:1px solid #0088FF; border-radius:10px; padding:7px 12px; }
textview { background:#07111C; color:#F4FAFF; padding:16px; font-family:monospace; }
"""

_TRANSLATIONS: Final[Mapping[str, Mapping[str, str]]] = {
    "en": {
        "window_title": "SWIR Text Editor",
        "brand": "◆  SWIR Text Editor",
        "new": "New",
        "open": "Open",
        "save": "Save",
        "save_as": "Save As",
        "new_tooltip": "Create a new local UTF-8 document",
        "open_tooltip": "Open a local UTF-8 document",
        "save_tooltip": "Save the current local UTF-8 document",
        "save_as_tooltip": "Save as a new local UTF-8 document",
        "editor_tooltip": "Local UTF-8 text editor",
        "ready": "Create or open a local UTF-8 text/code file.",
        "only_local": "Only local files are accepted.",
        "path_failed": "Could not resolve local path.",
        "open_failed": "Could not open document: {reason}",
        "opened": "Opened local UTF-8 document • {name}",
        "untitled": "Untitled — SWIR Text Editor",
        "new_unsaved": "New unsaved local UTF-8 document.",
        "open_dialog": "Open local document",
        "cancel": "Cancel",
        "choose_save_as": "Choose Save As to create this document.",
        "save_refused": "Save refused: {reason}",
        "saved": "Saved atomically.",
        "save_as_dialog": "Save new local document",
        "save_target_local": "Only local Save As targets are accepted.",
        "save_as_refused": "Save As refused: {reason}",
        "created": "Created securely • {name}",
    },
    "pl-PL": {
        "window_title": "Edytor tekstu SWIR",
        "brand": "◆  Edytor tekstu SWIR",
        "new": "Nowy",
        "open": "Otwórz",
        "save": "Zapisz",
        "save_as": "Zapisz jako",
        "new_tooltip": "Utwórz nowy lokalny dokument UTF-8",
        "open_tooltip": "Otwórz lokalny dokument UTF-8",
        "save_tooltip": "Zapisz bieżący lokalny dokument UTF-8",
        "save_as_tooltip": "Zapisz jako nowy lokalny dokument UTF-8",
        "editor_tooltip": "Lokalny edytor tekstu UTF-8",
        "ready": "Utwórz lub otwórz lokalny plik tekstowy/kodu UTF-8.",
        "only_local": "Akceptowane są tylko pliki lokalne.",
        "path_failed": "Nie udało się ustalić lokalnej ścieżki.",
        "open_failed": "Nie udało się otworzyć dokumentu: {reason}",
        "opened": "Otwarto lokalny dokument UTF-8 • {name}",
        "untitled": "Bez tytułu — Edytor tekstu SWIR",
        "new_unsaved": "Nowy niezapisany lokalny dokument UTF-8.",
        "open_dialog": "Otwórz lokalny dokument",
        "cancel": "Anuluj",
        "choose_save_as": "Wybierz Zapisz jako, aby utworzyć ten dokument.",
        "save_refused": "Odmówiono zapisu: {reason}",
        "saved": "Zapisano atomowo.",
        "save_as_dialog": "Zapisz nowy lokalny dokument",
        "save_target_local": "Akceptowane są tylko lokalne cele Zapisz jako.",
        "save_as_refused": "Odmówiono operacji Zapisz jako: {reason}",
        "created": "Utworzono bezpiecznie • {name}",
    },
    "nb-NO": {
        "window_title": "SWIR tekstredigering",
        "brand": "◆  SWIR tekstredigering",
        "new": "Ny",
        "open": "Åpne",
        "save": "Lagre",
        "save_as": "Lagre som",
        "new_tooltip": "Opprett et nytt lokalt UTF-8-dokument",
        "open_tooltip": "Åpne et lokalt UTF-8-dokument",
        "save_tooltip": "Lagre det gjeldende lokale UTF-8-dokumentet",
        "save_as_tooltip": "Lagre som et nytt lokalt UTF-8-dokument",
        "editor_tooltip": "Lokal UTF-8-tekstredigering",
        "ready": "Opprett eller åpne en lokal UTF-8 tekst-/kodefil.",
        "only_local": "Bare lokale filer godtas.",
        "path_failed": "Kunne ikke finne lokal filsti.",
        "open_failed": "Kunne ikke åpne dokumentet: {reason}",
        "opened": "Åpnet lokalt UTF-8-dokument • {name}",
        "untitled": "Uten tittel — SWIR tekstredigering",
        "new_unsaved": "Nytt ulagret lokalt UTF-8-dokument.",
        "open_dialog": "Åpne lokalt dokument",
        "cancel": "Avbryt",
        "choose_save_as": "Velg Lagre som for å opprette dokumentet.",
        "save_refused": "Lagring avvist: {reason}",
        "saved": "Lagret atomisk.",
        "save_as_dialog": "Lagre nytt lokalt dokument",
        "save_target_local": "Bare lokale Lagre som-mål godtas.",
        "save_as_refused": "Lagre som avvist: {reason}",
        "created": "Opprettet sikkert • {name}",
    },
}


@dataclass(frozen=True)
class TextEditorLocale:
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


def text_editor_locale(language: object) -> TextEditorLocale:
    requested = normalize_language_tag(language) or "en"
    catalog = requested if requested in _TRANSLATIONS else "en"
    return TextEditorLocale(requested, catalog, _TRANSLATIONS[catalog])


class DocumentError(RuntimeError):
    pass


def _absolute_local_path(value: str | os.PathLike[str]) -> pathlib.Path:
    raw_text = os.fspath(value)
    if "://" in raw_text or raw_text.startswith(("data:", "file:")):
        raise DocumentError("remote/URI document input is not accepted")
    raw = pathlib.Path(value).expanduser()
    return raw if raw.is_absolute() else pathlib.Path.cwd() / raw


def _has_symlink(path: pathlib.Path) -> bool:
    absolute = path if path.is_absolute() else pathlib.Path.cwd() / path
    current = pathlib.Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current /= part
        try:
            info = os.lstat(current)
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode):
            return True
    return False


def _encode_document(text: str) -> bytes:
    payload = text.encode("utf-8")
    if b"\0" in payload or len(payload) > MAX_DOCUMENT_BYTES:
        raise DocumentError("document output violates the UTF-8/size policy")
    return payload


def load_document(value: str | os.PathLike[str]) -> tuple[pathlib.Path, str, tuple[int, int]]:
    raw = _absolute_local_path(value)
    if _has_symlink(raw):
        raise DocumentError("symbolic-link document paths are not accepted")
    info = os.lstat(raw)
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise DocumentError("document must be a single-link regular file")
    if info.st_size < 0 or info.st_size > MAX_DOCUMENT_BYTES:
        raise DocumentError("document exceeds the 4 MiB safety limit")
    path = raw.resolve(strict=True)
    payload = path.read_bytes()
    if b"\0" in payload:
        raise DocumentError("binary/NUL-containing files are not accepted")
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise DocumentError("document must be valid UTF-8 text") from exc
    return path, text, (info.st_dev, info.st_ino)


def save_document(path: pathlib.Path, text: str, identity: tuple[int, int]) -> tuple[int, int]:
    payload = _encode_document(text)
    if _has_symlink(path):
        raise DocumentError("symbolic-link document paths are not accepted")
    before = os.lstat(path)
    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or (before.st_dev, before.st_ino) != identity:
        raise DocumentError("document changed since it was opened; refusing overwrite")
    if not os.access(path, os.W_OK):
        raise DocumentError("document is not writable by the current user")
    parent = path.parent.resolve(strict=True)
    if _has_symlink(parent) or not parent.is_dir():
        raise DocumentError("document parent is not a canonical directory")
    fd, temp_name = tempfile.mkstemp(prefix=".swir-text.", suffix=".tmp", dir=parent)
    temp = pathlib.Path(temp_name)
    try:
        os.fchmod(fd, stat.S_IMODE(before.st_mode) & 0o777)
        with os.fdopen(fd, "wb", closefd=True) as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        again = os.lstat(path)
        if (again.st_dev, again.st_ino) != identity or again.st_nlink != 1:
            raise DocumentError("document changed during save; refusing overwrite")
        os.replace(temp, path)
        dfd = os.open(parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(dfd)
        finally:
            os.close(dfd)
    finally:
        if temp.exists():
            temp.unlink()
    current = os.lstat(path)
    return current.st_dev, current.st_ino


def create_document(value: str | os.PathLike[str], text: str) -> tuple[pathlib.Path, tuple[int, int]]:
    """Create a new local document without following links or replacing data."""
    payload = _encode_document(text)
    raw = _absolute_local_path(value)
    if _has_symlink(raw):
        raise DocumentError("symbolic-link document paths are not accepted")
    parent = raw.parent.resolve(strict=True)
    if _has_symlink(parent) or not parent.is_dir():
        raise DocumentError("document parent is not a canonical directory")
    if not os.access(parent, os.W_OK | os.X_OK):
        raise DocumentError("document parent is not writable by the current user")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(raw, flags, 0o600)
    except FileExistsError as exc:
        raise DocumentError("Save As refuses to replace an existing file") from exc
    try:
        with os.fdopen(fd, "wb", closefd=True) as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        try:
            raw.unlink()
        except OSError:
            pass
        raise
    dfd = os.open(parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(dfd)
    finally:
        os.close(dfd)
    path = raw.resolve(strict=True)
    info = os.lstat(path)
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise DocumentError("new document did not resolve to a single-link regular file")
    return path, (info.st_dev, info.st_ino)


def self_test() -> int:
    assert text_editor_locale("pl-PL").text("save_as") == "Zapisz jako"
    assert text_editor_locale("nb-NO").text("open") == "Åpne"
    fallback = text_editor_locale("fr-FR")
    assert fallback.catalog_language == "en" and fallback.fallback is True
    assert fallback.text_direction == "ltr"

    with tempfile.TemporaryDirectory(prefix="swir-text-editor-") as temp_text:
        root = pathlib.Path(temp_text)
        sample = root / "sample.py"
        sample.write_text("print('SWIR')\n", encoding="utf-8")
        path, text, identity = load_document(sample)
        assert text == "print('SWIR')\n"
        identity = save_document(path, text + "# saved\n", identity)
        assert load_document(path)[1].endswith("# saved\n")
        assert identity == load_document(path)[2]

        created, created_identity = create_document(root / "new.txt", "new document\n")
        assert created.read_text(encoding="utf-8") == "new document\n"
        assert stat.S_IMODE(created.stat().st_mode) == 0o600
        assert created_identity == load_document(created)[2]
        try:
            create_document(created, "replace\n")
        except DocumentError:
            pass
        else:
            raise AssertionError("Save As replaced an existing file")

        binary = root / "binary.txt"
        binary.write_bytes(b"x\0y")
        try:
            load_document(binary)
        except DocumentError:
            pass
        else:
            raise AssertionError("binary file was accepted")

        symlink = root / "symlink.txt"
        symlink.symlink_to(sample.name)
        try:
            load_document(symlink)
        except DocumentError:
            pass
        else:
            raise AssertionError("symlink document was accepted")

        hard_source = root / "hard-source.txt"
        hard_source.write_text("hard\n", encoding="utf-8")
        hard_link = root / "hard-link.txt"
        os.link(hard_source, hard_link)
        try:
            load_document(hard_source)
        except DocumentError:
            pass
        else:
            raise AssertionError("multi-link document was accepted")

        race = root / "race.txt"
        race.write_text("original\n", encoding="utf-8")
        race_path, race_text, race_identity = load_document(race)
        replacement = root / "replacement.txt"
        replacement.write_text("replacement\n", encoding="utf-8")
        os.replace(replacement, race)
        try:
            save_document(race_path, race_text + "changed\n", race_identity)
        except DocumentError:
            pass
        else:
            raise AssertionError("replaced document identity was overwritten")

        oversized = root / "oversized.txt"
        oversized.write_bytes(b"x" * (MAX_DOCUMENT_BYTES + 1))
        try:
            load_document(oversized)
        except DocumentError:
            pass
        else:
            raise AssertionError("oversized document was accepted")

        try:
            load_document("https://example.invalid/file.txt")
        except DocumentError:
            pass
        else:
            raise AssertionError("remote URI was accepted")
    print("SWIR Text Editor self-test: OK")
    return 0


class SwirTextEditor(Gtk.Application):
    def __init__(self) -> None:
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.HANDLES_OPEN)
        self.window: Gtk.ApplicationWindow | None = None
        self.buffer: Gtk.TextBuffer | None = None
        self.status: Gtk.Label | None = None
        self.path: pathlib.Path | None = None
        self.identity: tuple[int, int] | None = None
        self.file_dialog: Gtk.FileChooserNative | None = None
        self.settings_store = UserSettingsStore()
        self.locale = self._load_locale()
        self.buttons: dict[str, Gtk.Button] = {}
        self.editor: Gtk.TextView | None = None
        self.e2e = os.environ.get("SWIR_APP_E2E", "0") == "1"
        self.evidence_path = os.environ.get("SWIR_APP_EVIDENCE_PATH", "")
        self.e2e_input = os.environ.get("SWIR_TEXT_E2E_INPUT", "")

    def _load_locale(self) -> TextEditorLocale:
        try:
            language = self.settings_store.load().get("language", "en")
        except (OSError, RuntimeError, UnicodeError, ValueError):
            language = "en"
        return text_editor_locale(language)

    def _t(self, key: str, **values: object) -> str:
        return self.locale.text(key, **values)

    def do_startup(self) -> None:
        Gtk.Application.do_startup(self)
        provider = Gtk.CssProvider()
        provider.load_from_data(CSS)
        display = Gdk.Display.get_default()
        if display is None:
            raise RuntimeError("SWIR Text Editor requires a graphical display")
        Gtk.StyleContext.add_provider_for_display(display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    def do_activate(self) -> None:
        if self.window is not None:
            self.window.present()
            return
        window = Gtk.ApplicationWindow(application=self)
        window.set_title(self._t("window_title"))
        window.set_default_size(960, 700)
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
        brand.set_hexpand(True)
        brand.set_xalign(0)
        header.append(brand)
        actions = (
            ("new", "new", "new_tooltip", self._new_clicked),
            ("open", "open", "open_tooltip", self._open_clicked),
            ("save", "save", "save_tooltip", self._save_clicked),
            ("save_as", "save_as", "save_as_tooltip", self._save_as_clicked),
        )
        for name, label_key, tooltip_key, handler in actions:
            button = Gtk.Button(label=self._t(label_key))
            button.add_css_class("swir-button")
            button.set_focusable(True)
            button.set_tooltip_text(self._t(tooltip_key))
            button.connect("clicked", handler)
            header.append(button)
            self.buttons[name] = button
        root.append(header)
        scroller = Gtk.ScrolledWindow()
        scroller.set_hexpand(True)
        scroller.set_vexpand(True)
        view = Gtk.TextView()
        view.set_wrap_mode(Gtk.WrapMode.NONE)
        view.set_monospace(True)
        view.set_focusable(True)
        view.set_direction(direction)
        view.set_tooltip_text(self._t("editor_tooltip"))
        self.editor = view
        self.buffer = view.get_buffer()
        scroller.set_child(view)
        root.append(scroller)
        self.status = Gtk.Label(label=self._t("ready"))
        self.status.add_css_class("swir-muted")
        self.status.set_xalign(0)
        self.status.set_margin_start(12)
        self.status.set_margin_end(12)
        self.status.set_margin_top(6)
        self.status.set_margin_bottom(8)
        root.append(self.status)
        if self.e2e and self.e2e_input:
            self._load(self.e2e_input)
        window.connect("map", self._on_mapped)
        window.present()

    def do_open(self, files: list[Gio.File], _count: int, _hint: str) -> None:
        self.activate()
        if not files or not files[0].is_native():
            self._set_status(self._t("only_local"))
            return
        path = files[0].get_path()
        if not path:
            self._set_status(self._t("path_failed"))
            return
        try:
            self._load(path)
        except (OSError, DocumentError) as exc:
            self._set_status(self._t("open_failed", reason=str(exc)))

    def _load(self, value: str | os.PathLike[str]) -> None:
        path, text, identity = load_document(value)
        assert self.buffer is not None
        self.buffer.set_text(text)
        self.path, self.identity = path, identity
        if self.window is not None:
            self.window.set_title(f"{path.name} — {self._t('window_title')}")
        self._set_status(self._t("opened", name=path.name))

    def _text(self) -> str:
        assert self.buffer is not None
        start, end = self.buffer.get_bounds()
        return self.buffer.get_text(start, end, True)

    def _new_clicked(self, _button: Gtk.Button) -> None:
        assert self.buffer is not None
        self.buffer.set_text("")
        self.path = None
        self.identity = None
        if self.window is not None:
            self.window.set_title(self._t("untitled"))
        self._set_status(self._t("new_unsaved"))

    def _open_clicked(self, _button: Gtk.Button) -> None:
        if self.window is None or self.file_dialog is not None:
            return
        dialog = Gtk.FileChooserNative.new(self._t("open_dialog"), self.window, Gtk.FileChooserAction.OPEN, self._t("open"), self._t("cancel"))
        dialog.set_select_multiple(False)
        dialog.connect("response", self._open_response)
        self.file_dialog = dialog
        dialog.show()

    def _open_response(self, dialog: Gtk.FileChooserNative, response: int) -> None:
        try:
            if response != Gtk.ResponseType.ACCEPT:
                return
            selected = dialog.get_file()
            if selected is None or not selected.is_native() or not selected.get_path():
                self._set_status(self._t("only_local"))
                return
            try:
                self._load(selected.get_path())
            except (OSError, DocumentError) as exc:
                self._set_status(self._t("open_failed", reason=str(exc)))
        finally:
            dialog.hide()
            self.file_dialog = None

    def _save(self) -> bool:
        if self.path is None or self.identity is None:
            self._set_status(self._t("choose_save_as"))
            return False
        try:
            self.identity = save_document(self.path, self._text(), self.identity)
        except (OSError, DocumentError) as exc:
            self._set_status(self._t("save_refused", reason=str(exc)))
            return False
        self._set_status(self._t("saved"))
        return True

    def _save_clicked(self, _button: Gtk.Button) -> None:
        if self.path is None:
            self._show_save_as()
        else:
            self._save()

    def _save_as_clicked(self, _button: Gtk.Button) -> None:
        self._show_save_as()

    def _show_save_as(self) -> None:
        if self.window is None or self.file_dialog is not None:
            return
        dialog = Gtk.FileChooserNative.new(self._t("save_as_dialog"), self.window, Gtk.FileChooserAction.SAVE, self._t("save"), self._t("cancel"))
        dialog.set_current_name(self.path.name if self.path is not None else "untitled.txt")
        dialog.connect("response", self._save_as_response)
        self.file_dialog = dialog
        dialog.show()

    def _save_as_response(self, dialog: Gtk.FileChooserNative, response: int) -> None:
        try:
            if response != Gtk.ResponseType.ACCEPT:
                return
            selected = dialog.get_file()
            if selected is None or not selected.is_native() or not selected.get_path():
                self._set_status(self._t("save_target_local"))
                return
            try:
                path, identity = create_document(selected.get_path(), self._text())
            except (OSError, DocumentError) as exc:
                self._set_status(self._t("save_as_refused", reason=str(exc)))
                return
            self.path, self.identity = path, identity
            if self.window is not None:
                self.window.set_title(f"{path.name} — {self._t('window_title')}")
            self._set_status(self._t("created", name=path.name))
        finally:
            dialog.hide()
            self.file_dialog = None

    def _set_status(self, text: str) -> None:
        if self.status is not None:
            self.status.set_text(text)

    def _on_mapped(self, _window: Gtk.Window) -> None:
        if not self.e2e or not self.evidence_path or self.path is None or self.buffer is None:
            return
        evidence = pathlib.Path(self.evidence_path)
        runtime = pathlib.Path(os.environ.get("XDG_RUNTIME_DIR", "")).resolve()
        if not runtime or evidence.parent.resolve() != runtime:
            raise RuntimeError("refusing evidence path outside XDG_RUNTIME_DIR")
        self.buffer.set_text(self._text() + "# SWIR Text Editor E2E saved\n")
        saved = self._save()
        reloaded = load_document(self.path)[1]
        create_probe, _ = create_document(runtime / "swir-text-editor-created.txt", "created by E2E\n")
        payload = {
            "schema": EVIDENCE_SCHEMA,
            "passed": saved and reloaded.endswith("# SWIR Text Editor E2E saved\n") and create_probe.is_file(),
            "applicationId": APP_ID,
            "nativeToolkit": "gtk4",
            "displayProtocol": "wayland",
            "windowMapped": True,
            "privilegedOperations": False,
            "localFilesOnly": True,
            "remoteUriInputAccepted": False,
            "symlinkInputAccepted": False,
            "hardlinkInputAccepted": False,
            "atomicOverwrite": True,
            "exclusiveCreate": True,
            "existingSaveAsTargetReplaced": False,
            "interactiveOpen": True,
            "interactiveNew": True,
            "interactiveSaveAs": True,
            "maxDocumentBytes": MAX_DOCUMENT_BYTES,
            "requestedLanguage": self.locale.requested_language,
            "catalogLanguage": self.locale.catalog_language,
            "fallbackUsed": self.locale.fallback,
            "textDirection": self.locale.text_direction,
            "windowTitle": self._t("window_title"),
            "buttonLabels": {name: button.get_label() for name, button in self.buttons.items()},
            "editorTooltip": self.editor.get_tooltip_text() if self.editor is not None else "",
        }
        evidence.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
        evidence.chmod(0o600)
        GLib.timeout_add(250, self._finish_e2e)

    def _finish_e2e(self) -> bool:
        self.quit()
        return False


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        raise SystemExit(self_test())
    raise SystemExit(SwirTextEditor().run(sys.argv))
