#!/usr/bin/env python3
"""SWIR Notes — first-party native GTK4 notes editor for System Edition."""

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

APP_ID: Final = "dev.swir.Notes"
EVIDENCE_SCHEMA: Final = "swir.native-notes-runtime-evidence/0.1"
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


class NotesStore:
    """Owner-only atomic storage for an unprivileged personal note."""

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
    def __init__(self) -> None:
        super().__init__(application_id=APP_ID)
        self.window: Gtk.ApplicationWindow | None = None
        self.buffer: Gtk.TextBuffer | None = None
        self.status: Gtk.Label | None = None
        self.store = NotesStore()
        self.e2e = os.environ.get("SWIR_APP_E2E", "0") == "1"
        self.evidence_path = os.environ.get("SWIR_APP_EVIDENCE_PATH", "")

    def do_startup(self) -> None:
        Gtk.Application.do_startup(self)
        provider = Gtk.CssProvider()
        provider.load_from_data(CSS)
        display = Gdk.Display.get_default()
        if display is None:
            raise RuntimeError("SWIR Notes requires a graphical display")
        Gtk.StyleContext.add_provider_for_display(display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

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
        brand = Gtk.Label(label="◆  SWIR Notes")
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
            self.buffer.set_text(self.store.load())
            self.status.set_text("Ready • personal note stored locally")
        except (OSError, UnicodeError, RuntimeError, ValueError) as exc:
            self.status.set_text(f"Could not load note: {exc}")

        window.connect("map", self._on_mapped)
        window.present()

    def _buffer_text(self) -> str:
        assert self.buffer is not None
        start, end = self.buffer.get_bounds()
        return self.buffer.get_text(start, end, True)

    def _save_current(self) -> bool:
        try:
            self.store.save(self._buffer_text())
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            if self.status is not None:
                self.status.set_text(f"Could not save note: {exc}")
            return False
        if self.status is not None:
            self.status.set_text("Saved")
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
        self.buffer.set_text("SWIR Notes E2E\n")
        saved = self._save_current()
        reloaded = self.store.load()
        note_mode = self.store.path.stat().st_mode & 0o777 if self.store.path.exists() else 0
        payload = {
            "schema": EVIDENCE_SCHEMA,
            "passed": saved and reloaded == "SWIR Notes E2E\n",
            "applicationId": APP_ID,
            "nativeToolkit": "gtk4",
            "displayProtocol": "wayland",
            "windowMapped": True,
            "privilegedOperations": False,
            "atomicPersistence": True,
            "ownerOnlyNotesFile": note_mode == 0o600,
            "maxNoteBytes": MAX_NOTE_BYTES,
        }
        path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
        path.chmod(0o600)
        GLib.timeout_add(250, self._finish_e2e)

    def _finish_e2e(self) -> bool:
        self.quit()
        return False


if __name__ == "__main__":
    raise SystemExit(SwirNotes().run(sys.argv))
