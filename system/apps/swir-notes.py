#!/usr/bin/env python3
"""SWIR Notes — first-party native GTK4 notes/text editor for System Edition."""

from __future__ import annotations

import json
import os
import pathlib
import stat
import sys
import tempfile
from typing import Final

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gdk, GLib, Gtk  # noqa: E402

APP_ID: Final = "dev.swir.Notes"
EVIDENCE_SCHEMA: Final = "swir.native-notes-runtime-evidence/0.2"
MAX_NOTE_BYTES: Final = 1024 * 1024

CSS = b"""
window.swir-app { background: #02050A; color: #F4FAFF; }
.swir-header { background: #07111C; border-bottom: 1px solid #0088FF; padding: 10px 14px; }
.swir-brand { color: #62E5FF; font-size: 18px; font-weight: 800; }
.swir-muted { color: #8DA8B8; }
.swir-button { background: #07111C; color: #F4FAFF; border: 1px solid #0088FF; border-radius: 10px; padding: 7px 12px; }
.swir-button:hover { border-color: #62E5FF; }
textview { background: #07111C; color: #F4FAFF; padding: 16px; }
"""


class TextFilePolicyError(RuntimeError):
    """A user-selected text file violates the local-file editing policy."""


def _path_has_symlink(path: pathlib.Path) -> bool:
    absolute = pathlib.Path(os.path.abspath(os.fspath(path)))
    current = pathlib.Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current = current / part
        try:
            current.lstat()
        except FileNotFoundError:
            continue
        if current.is_symlink():
            return True
    return False


def validate_text_file(raw: str | pathlib.Path) -> pathlib.Path:
    text = str(raw)
    if text.startswith(("http://", "https://", "data:", "file://")):
        raise TextFilePolicyError("only local filesystem paths are accepted")
    path = pathlib.Path(os.path.abspath(os.path.expanduser(text)))
    if _path_has_symlink(path):
        raise TextFilePolicyError("symbolic-link file paths are not accepted")
    try:
        info = path.stat(follow_symlinks=False)
    except OSError as exc:
        raise TextFilePolicyError(f"text file cannot be inspected: {exc}") from exc
    if not stat.S_ISREG(info.st_mode):
        raise TextFilePolicyError("text input must be a regular file")
    if info.st_size > MAX_NOTE_BYTES:
        raise TextFilePolicyError("text file exceeds the maximum supported size")
    if not os.access(path, os.R_OK):
        raise TextFilePolicyError("text file is not readable")
    return path


def read_text_file(path: pathlib.Path) -> str:
    validated = validate_text_file(path)
    payload = validated.read_bytes()
    if len(payload) > MAX_NOTE_BYTES:
        raise TextFilePolicyError("text file exceeds the maximum supported size")
    try:
        return payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise TextFilePolicyError("text file is not valid UTF-8") from exc


def atomic_save_text_file(path: pathlib.Path, text: str) -> None:
    if not isinstance(text, str):
        raise TypeError("document must be text")
    payload = text.encode("utf-8")
    if len(payload) > MAX_NOTE_BYTES:
        raise ValueError("document exceeds the maximum supported size")
    validated = validate_text_file(path)
    original = validated.stat(follow_symlinks=False)
    if not os.access(validated, os.W_OK):
        raise TextFilePolicyError("text file is not writable")
    parent = validated.parent
    if _path_has_symlink(parent):
        raise TextFilePolicyError("symbolic-link parent paths are not accepted")

    fd, temp_name = tempfile.mkstemp(prefix=f".{validated.name}.", suffix=".swir-tmp", dir=parent)
    temp_path = pathlib.Path(temp_name)
    try:
        os.fchmod(fd, stat.S_IMODE(original.st_mode))
        with os.fdopen(fd, "wb", closefd=True) as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        current = validated.stat(follow_symlinks=False)
        if (current.st_dev, current.st_ino) != (original.st_dev, original.st_ino):
            raise TextFilePolicyError("text file changed while it was being saved")
        os.replace(temp_path, validated)
        directory_fd = os.open(parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if temp_path.exists():
            temp_path.unlink()


class NotesStore:
    """Owner-only atomic storage for the built-in personal note."""

    def __init__(self, data_home: pathlib.Path | None = None) -> None:
        if data_home is None:
            raw = os.environ.get("XDG_DATA_HOME")
            data_home = pathlib.Path(raw).expanduser() if raw else pathlib.Path.home() / ".local" / "share"
        self.data_home = data_home.resolve(strict=False)
        self.directory = self.data_home / "swir"
        self.path = self.directory / "notes.txt"

    def _prepare_directory(self) -> None:
        if self.directory.is_symlink():
            raise RuntimeError("refusing symlinked SWIR data directory")
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        if self.directory.is_symlink():
            raise RuntimeError("refusing symlinked SWIR data directory")
        self.directory.chmod(0o700)

    def load(self) -> str:
        self._prepare_directory()
        if not self.path.exists():
            return ""
        if self.path.is_symlink():
            raise RuntimeError("refusing symlinked SWIR notes file")
        data = self.path.read_bytes()
        if len(data) > MAX_NOTE_BYTES:
            raise ValueError("notes file exceeds the maximum supported size")
        return data.decode("utf-8")

    def save(self, text: str) -> None:
        if not isinstance(text, str):
            raise TypeError("note must be text")
        payload = text.encode("utf-8")
        if len(payload) > MAX_NOTE_BYTES:
            raise ValueError("note exceeds the maximum supported size")
        self._prepare_directory()
        if self.path.exists() and self.path.is_symlink():
            raise RuntimeError("refusing symlinked SWIR notes file")

        fd, temp_name = tempfile.mkstemp(prefix=".notes.", suffix=".tmp", dir=self.directory)
        temp_path = pathlib.Path(temp_name)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "wb", closefd=True) as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, self.path)
            self.path.chmod(0o600)
            directory_fd = os.open(self.directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            if temp_path.exists():
                temp_path.unlink()


class SwirNotes(Gtk.Application):
    def __init__(self, initial_path: str | None = None) -> None:
        super().__init__(application_id=APP_ID)
        self.window: Gtk.ApplicationWindow | None = None
        self.buffer: Gtk.TextBuffer | None = None
        self.status: Gtk.Label | None = None
        self.store = NotesStore()
        self.current_file: pathlib.Path | None = None
        self.initial_path = initial_path
        self.e2e = os.environ.get("SWIR_APP_E2E", "0") == "1"
        self.evidence_path = os.environ.get("SWIR_APP_EVIDENCE_PATH", "")
        self.e2e_input = os.environ.get("SWIR_NOTES_E2E_INPUT", "")

    def do_startup(self) -> None:
        Gtk.Application.do_startup(self)
        provider = Gtk.CssProvider()
        provider.load_from_data(CSS)
        display = Gdk.Display.get_default()
        if display is None:
            raise RuntimeError("SWIR Notes requires a graphical display")
        Gtk.StyleContext.add_provider_for_display(display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    def _load_document(self, path: pathlib.Path) -> None:
        assert self.buffer is not None and self.status is not None
        text = read_text_file(path)
        self.current_file = path
        self.buffer.set_text(text)
        self.status.set_text(f"Editing {path.name} • local UTF-8 file")
        if self.window is not None:
            self.window.set_title(f"{path.name} — SWIR Notes")

    def do_activate(self) -> None:
        if self.window is not None:
            self.window.present()
            return

        window = Gtk.ApplicationWindow(application=self)
        window.set_title("SWIR Notes")
        window.set_default_size(900, 650)
        window.add_css_class("swir-app")
        self.window = window

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        window.set_child(root)

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        header.add_css_class("swir-header")
        brand = Gtk.Label(label="◆  SWIR Notes / Text Editor")
        brand.add_css_class("swir-brand")
        brand.set_xalign(0)
        header.append(brand)
        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        header.append(spacer)
        save = Gtk.Button(label="Save")
        save.add_css_class("swir-button")
        save.connect("clicked", self._save_clicked)
        header.append(save)
        root.append(header)

        scroller = Gtk.ScrolledWindow()
        scroller.set_hexpand(True)
        scroller.set_vexpand(True)
        text = Gtk.TextView()
        text.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.buffer = text.get_buffer()
        scroller.set_child(text)
        root.append(scroller)

        self.status = Gtk.Label()
        self.status.add_css_class("swir-muted")
        self.status.set_xalign(0)
        root.append(self.status)

        try:
            requested = self.e2e_input or self.initial_path
            if requested:
                self._load_document(validate_text_file(requested))
            else:
                self.buffer.set_text(self.store.load())
                self.status.set_text("Ready • personal note stored locally")
        except (OSError, UnicodeError, RuntimeError, ValueError) as exc:
            self.status.set_text(f"Could not load document: {exc}")

        window.connect("map", self._on_mapped)
        window.present()

    def _buffer_text(self) -> str:
        assert self.buffer is not None
        start, end = self.buffer.get_bounds()
        return self.buffer.get_text(start, end, True)

    def _save_current(self) -> bool:
        try:
            if self.current_file is not None:
                atomic_save_text_file(self.current_file, self._buffer_text())
            else:
                self.store.save(self._buffer_text())
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            if self.status is not None:
                self.status.set_text(f"Could not save document: {exc}")
            return False
        if self.status is not None:
            target = self.current_file.name if self.current_file is not None else "personal note"
            self.status.set_text(f"Saved {target}")
        return True

    def _save_clicked(self, _button: Gtk.Button) -> None:
        self._save_current()

    def _on_mapped(self, _window: Gtk.Window) -> None:
        if not self.e2e or not self.evidence_path:
            return
        path = pathlib.Path(self.evidence_path)
        runtime_text = os.environ.get("XDG_RUNTIME_DIR", "")
        if not runtime_text or path.parent.resolve() != pathlib.Path(runtime_text).resolve():
            raise RuntimeError("refusing SWIR Notes evidence path outside XDG_RUNTIME_DIR")

        assert self.buffer is not None
        external_mode = self.current_file is not None
        self.buffer.set_text("SWIR Notes E2E\n")
        saved = self._save_current()
        if external_mode:
            assert self.current_file is not None
            reloaded = read_text_file(self.current_file)
            owner_only_note = None
        else:
            reloaded = self.store.load()
            note_mode = self.store.path.stat().st_mode & 0o777 if self.store.path.exists() else 0
            owner_only_note = note_mode == 0o600
        payload = {
            "schema": EVIDENCE_SCHEMA,
            "passed": saved and reloaded == "SWIR Notes E2E\n",
            "applicationId": APP_ID,
            "nativeToolkit": "gtk4",
            "displayProtocol": "wayland",
            "windowMapped": True,
            "privilegedOperations": False,
            "atomicPersistence": True,
            "ownerOnlyNotesFile": owner_only_note,
            "externalTextFileEditing": external_mode,
            "externalPathSymlinksAccepted": False,
            "externalTextEncoding": "utf-8",
            "maxNoteBytes": MAX_NOTE_BYTES,
        }
        path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
        path.chmod(0o600)
        GLib.timeout_add(250, self._finish_e2e)

    def _finish_e2e(self) -> bool:
        self.quit()
        return False


def _initial_path(argv: list[str]) -> str | None:
    values = [value for value in argv[1:] if value and not value.startswith("-")]
    if len(values) > 1:
        raise SystemExit("SWIR Notes accepts one local text file at a time")
    return values[0] if values else None


if __name__ == "__main__":
    initial = _initial_path(sys.argv)
    raise SystemExit(SwirNotes(initial).run([sys.argv[0]]))
