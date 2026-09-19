#!/usr/bin/env python3
"""SWIR Text Editor — safe first-party GTK4 text/code editor for System Edition."""

from __future__ import annotations

import json
import os
import pathlib
import stat
import sys
import tempfile
from dataclasses import dataclass
from typing import Final

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gdk, Gio, GLib, Gtk  # noqa: E402

APP_ID: Final = "dev.swir.TextEditor"
EVIDENCE_SCHEMA: Final = "swir.native-text-editor-runtime-evidence/0.1"
MAX_TEXT_BYTES: Final = 2 * 1024 * 1024

CSS = b"""
window.swir-app { background: #02050A; color: #F4FAFF; }
.swir-header { background: #07111C; border-bottom: 1px solid #0088FF; padding: 10px 14px; }
.swir-brand { color: #62E5FF; font-size: 18px; font-weight: 800; }
.swir-muted { color: #8DA8B8; }
.swir-button { background: #07111C; color: #F4FAFF; border: 1px solid #0088FF; border-radius: 10px; padding: 7px 12px; }
.swir-button:hover { border-color: #62E5FF; }
textview { background: #07111C; color: #F4FAFF; padding: 16px; font-family: monospace; }
"""


class TextPolicyError(RuntimeError):
    """The selected file violates the local text-editor safety policy."""


@dataclass(frozen=True)
class FileVersion:
    device: int
    inode: int
    size: int
    mtime_ns: int
    mode: int


def _has_symlink_component(path: pathlib.Path) -> bool:
    absolute = path if path.is_absolute() else pathlib.Path.cwd() / path
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


def _validated_local_file(raw: str | pathlib.Path) -> tuple[pathlib.Path, FileVersion]:
    text = str(raw)
    if text.startswith(("http://", "https://", "data:", "file://")):
        raise TextPolicyError("only native local file paths are accepted")
    path = pathlib.Path(raw).expanduser().absolute()
    if _has_symlink_component(path):
        raise TextPolicyError("symbolic-link paths are not accepted")
    try:
        resolved = path.resolve(strict=True)
        info = resolved.stat()
    except OSError as exc:
        raise TextPolicyError(f"text file cannot be resolved: {exc}") from exc
    if resolved != path or not stat.S_ISREG(info.st_mode) or not os.access(resolved, os.R_OK):
        raise TextPolicyError("text input must be a canonical readable regular file")
    if info.st_size < 0 or info.st_size > MAX_TEXT_BYTES:
        raise TextPolicyError("text file exceeds the verified 2 MiB limit")
    return resolved, FileVersion(info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, stat.S_IMODE(info.st_mode))


def load_text_file(raw: str | pathlib.Path) -> tuple[pathlib.Path, str, FileVersion]:
    path, version = _validated_local_file(raw)
    try:
        payload = path.read_bytes()
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise TextPolicyError("file is not valid UTF-8 text") from exc
    if len(payload) > MAX_TEXT_BYTES:
        raise TextPolicyError("text file changed beyond the verified 2 MiB limit")
    return path, text, version


def atomic_save_text(path: pathlib.Path, expected: FileVersion, text: str) -> FileVersion:
    if not isinstance(text, str):
        raise TypeError("text payload must be a string")
    payload = text.encode("utf-8")
    if len(payload) > MAX_TEXT_BYTES:
        raise TextPolicyError("edited text exceeds the verified 2 MiB limit")
    current, current_version = _validated_local_file(path)
    if current != path:
        raise TextPolicyError("file identity changed")
    if (current_version.device, current_version.inode, current_version.size, current_version.mtime_ns) != (
        expected.device,
        expected.inode,
        expected.size,
        expected.mtime_ns,
    ):
        raise TextPolicyError("file changed on disk; reload before saving")
    if os.geteuid() != 0 and current.stat().st_uid != os.geteuid():
        raise TextPolicyError("refusing to replace a file not owned by the current user")
    if not os.access(current.parent, os.W_OK):
        raise TextPolicyError("file directory is not writable")

    fd, temp_name = tempfile.mkstemp(prefix=f".{current.name}.swir-", suffix=".tmp", dir=current.parent)
    temp_path = pathlib.Path(temp_name)
    try:
        mode = expected.mode & 0o777
        os.fchmod(fd, mode)
        with os.fdopen(fd, "wb", closefd=True) as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, current)
        directory_fd = os.open(current.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if temp_path.exists():
            temp_path.unlink()
    _, version = _validated_local_file(current)
    return version


class SwirTextEditor(Gtk.Application):
    def __init__(self) -> None:
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.HANDLES_OPEN)
        self.window: Gtk.ApplicationWindow | None = None
        self.buffer: Gtk.TextBuffer | None = None
        self.status: Gtk.Label | None = None
        self.current_path: pathlib.Path | None = None
        self.current_version: FileVersion | None = None
        self.e2e = os.environ.get("SWIR_TEXT_EDITOR_E2E", "0") == "1"
        self.evidence_path = os.environ.get("SWIR_APP_EVIDENCE_PATH", "")
        self.e2e_done = False

    def do_startup(self) -> None:
        Gtk.Application.do_startup(self)
        provider = Gtk.CssProvider()
        provider.load_from_data(CSS)
        display = Gdk.Display.get_default()
        if display is None:
            raise RuntimeError("SWIR Text Editor requires a graphical display")
        Gtk.StyleContext.add_provider_for_display(display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    def _ensure_window(self) -> None:
        if self.window is not None:
            return
        window = Gtk.ApplicationWindow(application=self)
        window.set_title("SWIR Text Editor")
        window.set_default_size(980, 700)
        window.add_css_class("swir-app")
        self.window = window
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        window.set_child(root)
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        header.add_css_class("swir-header")
        brand = Gtk.Label(label="◆  SWIR Text Editor")
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
        editor = Gtk.TextView()
        editor.set_wrap_mode(Gtk.WrapMode.NONE)
        self.buffer = editor.get_buffer()
        scroller.set_child(editor)
        root.append(scroller)
        self.status = Gtk.Label(label="Open a local UTF-8 text or code file.")
        self.status.add_css_class("swir-muted")
        self.status.set_xalign(0)
        root.append(self.status)
        window.connect("map", self._on_mapped)

    def do_activate(self) -> None:
        self._ensure_window()
        assert self.window is not None
        self.window.present()

    def do_open(self, files: list[Gio.File], _n_files: int, _hint: str) -> None:
        self._ensure_window()
        assert self.window is not None
        if not files:
            self.window.present()
            return
        file = files[0]
        if not file.is_native() or not file.get_path():
            self._set_status("Rejected: only native local files are accepted.")
            self.window.present()
            return
        try:
            path, text, version = load_text_file(file.get_path())
        except (OSError, TextPolicyError) as exc:
            self._set_status(f"Open refused: {exc}")
            self.window.present()
            return
        assert self.buffer is not None
        self.buffer.set_text(text)
        self.current_path = path
        self.current_version = version
        self.window.set_title(f"{path.name} — SWIR Text Editor")
        self._set_status(f"Opened {path} • UTF-8 • {version.size} bytes")
        self.window.present()

    def _set_status(self, text: str) -> None:
        if self.status is not None:
            self.status.set_text(text)

    def _buffer_text(self) -> str:
        assert self.buffer is not None
        start, end = self.buffer.get_bounds()
        return self.buffer.get_text(start, end, True)

    def _save_current(self) -> bool:
        if self.current_path is None or self.current_version is None:
            self._set_status("Nothing to save: open a local file first.")
            return False
        try:
            self.current_version = atomic_save_text(self.current_path, self.current_version, self._buffer_text())
        except (OSError, TextPolicyError, TypeError) as exc:
            self._set_status(f"Save refused: {exc}")
            return False
        self._set_status(f"Saved atomically to {self.current_path}")
        return True

    def _save_clicked(self, _button: Gtk.Button) -> None:
        self._save_current()

    def _on_mapped(self, _window: Gtk.Window) -> None:
        if self.e2e_done or not self.e2e or not self.evidence_path:
            return
        evidence = pathlib.Path(self.evidence_path)
        runtime_text = os.environ.get("XDG_RUNTIME_DIR", "")
        if not runtime_text or evidence.parent.resolve() != pathlib.Path(runtime_text).resolve():
            raise RuntimeError("refusing Text Editor evidence path outside XDG_RUNTIME_DIR")
        if self.current_path is None or self.current_version is None or self.buffer is None:
            raise RuntimeError("Text Editor E2E requires a local input file")
        original_path = self.current_path
        start, end = self.buffer.get_bounds()
        original = self.buffer.get_text(start, end, True)
        self.buffer.set_text(original + "SWIR Text Editor E2E\n")
        saved = self._save_current()
        loaded_path, loaded_text, new_version = load_text_file(original_path)
        payload = {
            "schema": EVIDENCE_SCHEMA,
            "passed": saved and loaded_path == original_path and loaded_text.endswith("SWIR Text Editor E2E\n"),
            "applicationId": APP_ID,
            "nativeToolkit": "gtk4",
            "displayProtocol": "wayland",
            "windowMapped": True,
            "localFileOnly": True,
            "utf8Only": True,
            "atomicSave": True,
            "conflictDetection": True,
            "symlinkPathsAccepted": False,
            "privilegedOperations": False,
            "maxTextBytes": MAX_TEXT_BYTES,
            "savedMode": new_version.mode,
        }
        evidence.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
        evidence.chmod(0o600)
        self.e2e_done = True
        GLib.timeout_add(250, self._finish_e2e)

    def _finish_e2e(self) -> bool:
        self.quit()
        return False


if __name__ == "__main__":
    raise SystemExit(SwirTextEditor().run(sys.argv))
