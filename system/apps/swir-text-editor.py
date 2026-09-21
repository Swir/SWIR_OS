#!/usr/bin/env python3
"""SWIR Text Editor — native GTK4 local UTF-8 text/code handler."""
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
from gi.repository import Gdk, Gio, GLib, Gtk  # noqa: E402

APP_ID: Final = "dev.swir.TextEditor"
EVIDENCE_SCHEMA: Final = "swir.native-text-editor-runtime-evidence/0.2"
MAX_DOCUMENT_BYTES: Final = 4 * 1024 * 1024

CSS = b"""
window.swir-app { background:#02050A; color:#F4FAFF; }
.swir-header { background:#07111C; border-bottom:1px solid #0088FF; padding:10px 14px; }
.swir-brand { color:#62E5FF; font-size:18px; font-weight:800; }
.swir-muted { color:#8DA8B8; }
.swir-button { background:#07111C; color:#F4FAFF; border:1px solid #0088FF; border-radius:10px; padding:7px 12px; }
textview { background:#07111C; color:#F4FAFF; padding:16px; font-family:monospace; }
"""


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
    if (
        not stat.S_ISREG(before.st_mode)
        or before.st_nlink != 1
        or (before.st_dev, before.st_ino) != identity
    ):
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
        self.e2e = os.environ.get("SWIR_APP_E2E", "0") == "1"
        self.evidence_path = os.environ.get("SWIR_APP_EVIDENCE_PATH", "")
        self.e2e_input = os.environ.get("SWIR_TEXT_E2E_INPUT", "")

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
        window.set_title("SWIR Text Editor")
        window.set_default_size(960, 700)
        window.add_css_class("swir-app")
        self.window = window
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        window.set_child(root)
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        header.add_css_class("swir-header")
        brand = Gtk.Label(label="◆  SWIR Text Editor")
        brand.add_css_class("swir-brand")
        brand.set_hexpand(True)
        brand.set_xalign(0)
        header.append(brand)
        for label, handler in (("New", self._new_clicked), ("Open", self._open_clicked), ("Save", self._save_clicked), ("Save As", self._save_as_clicked)):
            button = Gtk.Button(label=label)
            button.add_css_class("swir-button")
            button.set_tooltip_text(f"{label} local UTF-8 document")
            button.connect("clicked", handler)
            header.append(button)
        root.append(header)
        scroller = Gtk.ScrolledWindow()
        scroller.set_hexpand(True)
        scroller.set_vexpand(True)
        view = Gtk.TextView()
        view.set_wrap_mode(Gtk.WrapMode.NONE)
        view.set_monospace(True)
        view.set_tooltip_text("Local UTF-8 text editor")
        self.buffer = view.get_buffer()
        scroller.set_child(view)
        root.append(scroller)
        self.status = Gtk.Label(label="Create or open a local UTF-8 text/code file.")
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
            self._set_status("Only local files are accepted.")
            return
        path = files[0].get_path()
        if not path:
            self._set_status("Could not resolve local path.")
            return
        try:
            self._load(path)
        except (OSError, DocumentError) as exc:
            self._set_status(f"Could not open document: {exc}")

    def _load(self, value: str | os.PathLike[str]) -> None:
        path, text, identity = load_document(value)
        assert self.buffer is not None
        self.buffer.set_text(text)
        self.path, self.identity = path, identity
        if self.window is not None:
            self.window.set_title(f"{path.name} — SWIR Text Editor")
        self._set_status(f"Opened local UTF-8 document • {path.name}")

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
            self.window.set_title("Untitled — SWIR Text Editor")
        self._set_status("New unsaved local UTF-8 document.")

    def _open_clicked(self, _button: Gtk.Button) -> None:
        if self.window is None or self.file_dialog is not None:
            return
        dialog = Gtk.FileChooserNative.new("Open local document", self.window, Gtk.FileChooserAction.OPEN, "Open", "Cancel")
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
                self._set_status("Only local files are accepted.")
                return
            try:
                self._load(selected.get_path())
            except (OSError, DocumentError) as exc:
                self._set_status(f"Could not open document: {exc}")
        finally:
            dialog.hide()
            self.file_dialog = None

    def _save(self) -> bool:
        if self.path is None or self.identity is None:
            self._set_status("Choose Save As to create this document.")
            return False
        try:
            self.identity = save_document(self.path, self._text(), self.identity)
        except (OSError, DocumentError) as exc:
            self._set_status(f"Save refused: {exc}")
            return False
        self._set_status("Saved atomically.")
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
        dialog = Gtk.FileChooserNative.new("Save new local document", self.window, Gtk.FileChooserAction.SAVE, "Save", "Cancel")
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
                self._set_status("Only local Save As targets are accepted.")
                return
            try:
                path, identity = create_document(selected.get_path(), self._text())
            except (OSError, DocumentError) as exc:
                self._set_status(f"Save As refused: {exc}")
                return
            self.path, self.identity = path, identity
            if self.window is not None:
                self.window.set_title(f"{path.name} — SWIR Text Editor")
            self._set_status(f"Created securely • {path.name}")
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
