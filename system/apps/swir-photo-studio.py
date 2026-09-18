#!/usr/bin/env python3
"""SWIR Photo Studio — native GTK4 image viewer/editor for System Edition.

The application is unprivileged and deliberately non-destructive: source images
are opened read-only, edits stay in memory with bounded undo/redo history, and
users export an explicit copy in PNG/JPEG/WebP. There is no package mutation,
self-updater, sudo/pkexec shortcut, or remote-URI input path.
"""

from __future__ import annotations

import json
import mimetypes
import os
import pathlib
import sys
import tempfile
from dataclasses import dataclass
from typing import Final

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Gdk, GdkPixbuf, Gio, GLib, Gtk  # noqa: E402

APP_ID: Final = "dev.swir.PhotoStudio"
EVIDENCE_SCHEMA: Final = "swir.native-photo-studio-runtime-evidence/0.1"
MAX_INPUT_BYTES: Final = 64 * 1024 * 1024
MAX_PIXELS: Final = 40_000_000
MAX_HISTORY: Final = 24
MAX_PATH_BYTES: Final = 4096
SUPPORTED_INPUT_SUFFIXES: Final = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff"}
EXPORT_FORMATS: Final = {
    ".png": ("png", [], []),
    ".jpg": ("jpeg", ["quality"], ["92"]),
    ".jpeg": ("jpeg", ["quality"], ["92"]),
    ".webp": ("webp", ["quality"], ["90"]),
}

CSS = b"""
window.swir-app { background: #02050A; color: #F4FAFF; }
.swir-header { background: #07111C; border-bottom: 1px solid #0088FF; padding: 10px 12px; }
.swir-brand { color: #62E5FF; font-size: 20px; font-weight: 800; }
.swir-muted { color: #8DA8B8; }
.swir-panel { background: #07111C; border: 1px solid rgba(98,229,255,0.22); border-radius: 14px; padding: 10px; }
.swir-button { background: #07111C; color: #F4FAFF; border: 1px solid rgba(0,136,255,0.65); border-radius: 9px; padding: 6px 10px; }
.swir-button:hover { border-color: #62E5FF; }
.swir-primary { background: #0088FF; color: #F4FAFF; border-radius: 9px; padding: 6px 12px; font-weight: 700; }
"""


class PhotoPolicyError(RuntimeError):
    pass


def _path_has_symlink(path: pathlib.Path, *, allow_missing_leaf: bool = False) -> bool:
    absolute = path if path.is_absolute() else (pathlib.Path.cwd() / path)
    current = pathlib.Path(absolute.anchor)
    parts = absolute.parts[1:]
    for index, part in enumerate(parts):
        current = current / part
        try:
            current.lstat()
        except FileNotFoundError:
            if allow_missing_leaf and index == len(parts) - 1:
                return False
            continue
        if current.is_symlink():
            return True
    return False


def _validated_local_image(raw: str | pathlib.Path) -> pathlib.Path:
    text = str(raw)
    if text.startswith(("http://", "https://", "data:", "file://")):
        raise PhotoPolicyError("remote/URI image input is not accepted")
    path = pathlib.Path(raw).expanduser()
    if len(os.fsencode(path)) > MAX_PATH_BYTES:
        raise PhotoPolicyError("image path is too long")
    path = path.absolute()
    if _path_has_symlink(path):
        raise PhotoPolicyError("symbolic-link image paths are not accepted")
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise PhotoPolicyError(f"image path cannot be resolved: {exc}") from exc
    if resolved != path:
        raise PhotoPolicyError("image path must be canonical")
    if not resolved.is_file() or not os.access(resolved, os.R_OK):
        raise PhotoPolicyError("image must be a readable regular file")
    size = resolved.stat().st_size
    if size <= 0 or size > MAX_INPUT_BYTES:
        raise PhotoPolicyError("image file size is outside the verified bound")
    mime, _ = mimetypes.guess_type(resolved.name)
    if resolved.suffix.lower() not in SUPPORTED_INPUT_SUFFIXES and not (mime or "").startswith("image/"):
        raise PhotoPolicyError("unsupported image type")
    return resolved


def _load_pixbuf(path: pathlib.Path) -> GdkPixbuf.Pixbuf:
    try:
        pixbuf = GdkPixbuf.Pixbuf.new_from_file(str(path))
        oriented = pixbuf.apply_embedded_orientation()
        if oriented is not None:
            pixbuf = oriented
    except GLib.Error as exc:
        raise PhotoPolicyError(f"image decode failed: {exc.message}") from exc
    width, height = pixbuf.get_width(), pixbuf.get_height()
    if width <= 0 or height <= 0 or width * height > MAX_PIXELS:
        raise PhotoPolicyError("decoded image dimensions exceed the verified bound")
    return pixbuf


def _validated_export_path(raw: str | pathlib.Path) -> pathlib.Path:
    path = pathlib.Path(raw).expanduser().absolute()
    if len(os.fsencode(path)) > MAX_PATH_BYTES:
        raise PhotoPolicyError("export path is too long")
    if path.suffix.lower() not in EXPORT_FORMATS:
        raise PhotoPolicyError("export extension must be .png, .jpg, .jpeg or .webp")
    parent = path.parent
    if not parent.exists() or not parent.is_dir() or _path_has_symlink(parent):
        raise PhotoPolicyError("export directory must be an existing non-symlink directory")
    if path.exists() and (not path.is_file() or path.is_symlink()):
        raise PhotoPolicyError("refusing non-regular or symlink export destination")
    if not os.access(parent, os.W_OK):
        raise PhotoPolicyError("export directory is not writable")
    return path


def _atomic_export(pixbuf: GdkPixbuf.Pixbuf, destination: pathlib.Path) -> None:
    destination = _validated_export_path(destination)
    fmt, keys, values = EXPORT_FORMATS[destination.suffix.lower()]
    fd, tmp_name = tempfile.mkstemp(prefix=f".{destination.name}.", suffix=destination.suffix, dir=destination.parent)
    os.close(fd)
    tmp = pathlib.Path(tmp_name)
    try:
        try:
            pixbuf.savev(str(tmp), fmt, keys, values)
        except GLib.Error as exc:
            raise PhotoPolicyError(f"image export failed: {exc.message}") from exc
        os.chmod(tmp, 0o600)
        try:
            sync_fd = os.open(tmp, os.O_RDONLY)
            try:
                os.fsync(sync_fd)
            finally:
                os.close(sync_fd)
        except OSError:
            pass
        os.replace(tmp, destination)
        os.chmod(destination, 0o600)
    finally:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass


@dataclass
class EditHistory:
    states: list[GdkPixbuf.Pixbuf]
    index: int

    @classmethod
    def from_pixbuf(cls, pixbuf: GdkPixbuf.Pixbuf) -> "EditHistory":
        return cls([pixbuf.copy()], 0)

    @property
    def current(self) -> GdkPixbuf.Pixbuf:
        return self.states[self.index]

    @property
    def can_undo(self) -> bool:
        return self.index > 0

    @property
    def can_redo(self) -> bool:
        return self.index + 1 < len(self.states)

    def push(self, pixbuf: GdkPixbuf.Pixbuf) -> None:
        del self.states[self.index + 1 :]
        self.states.append(pixbuf.copy())
        if len(self.states) > MAX_HISTORY:
            del self.states[: len(self.states) - MAX_HISTORY]
        self.index = len(self.states) - 1

    def undo(self) -> GdkPixbuf.Pixbuf:
        if self.can_undo:
            self.index -= 1
        return self.current

    def redo(self) -> GdkPixbuf.Pixbuf:
        if self.can_redo:
            self.index += 1
        return self.current


class SwirPhotoStudio(Gtk.Application):
    def __init__(self) -> None:
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.HANDLES_OPEN | Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        self.window: Gtk.ApplicationWindow | None = None
        self.picture: Gtk.Picture | None = None
        self.status_label: Gtk.Label | None = None
        self.info_label: Gtk.Label | None = None
        self.undo_button: Gtk.Button | None = None
        self.redo_button: Gtk.Button | None = None
        self.history: EditHistory | None = None
        self.source_path: pathlib.Path | None = None
        self._e2e = os.environ.get("SWIR_APP_E2E") == "1"
        self._evidence_path = os.environ.get("SWIR_APP_EVIDENCE_PATH", "")
        self._e2e_input = os.environ.get("SWIR_PHOTO_E2E_IMAGE", "")
        self._e2e_export_dir = os.environ.get("SWIR_PHOTO_E2E_EXPORT_DIR", "")
        self._evidence_written = False

    def do_startup(self) -> None:
        Gtk.Application.do_startup(self)
        provider = Gtk.CssProvider()
        provider.load_from_data(CSS)
        display = Gdk.Display.get_default()
        if display is None:
            raise RuntimeError("SWIR Photo Studio requires an active graphical display")
        Gtk.StyleContext.add_provider_for_display(display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        for name, accelerator, callback in (
            ("open", "<Primary>O", self._choose_open),
            ("export", "<Primary><Shift>S", self._choose_export),
            ("undo", "<Primary>Z", lambda *_: self._undo()),
            ("redo", "<Primary><Shift>Z", lambda *_: self._redo()),
        ):
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", callback)
            self.add_action(action)
            self.set_accels_for_action(f"app.{name}", [accelerator])

    def do_command_line(self, command_line: Gio.ApplicationCommandLine) -> int:
        args = command_line.get_arguments()[1:]
        requested: pathlib.Path | None = None
        index = 0
        while index < len(args):
            if args[index] == "--open" and index + 1 < len(args):
                try:
                    requested = _validated_local_image(args[index + 1])
                except PhotoPolicyError as exc:
                    print(f"SWIR Photo Studio refused image: {exc}", file=sys.stderr)
                    return 64
                index += 2
                continue
            index += 1
        self.activate()
        if requested is not None:
            self._open_path(requested)
        return 0

    def do_open(self, files, _n_files: int, _hint: str) -> None:
        self.activate()
        for gio_file in files:
            text = gio_file.get_path()
            if not text:
                self._set_status("Only local image files are accepted.")
                return
            try:
                self._open_path(_validated_local_image(text))
            except PhotoPolicyError as exc:
                self._set_status(str(exc))
            break

    def do_activate(self) -> None:
        if self.window is not None:
            self.window.present()
            return
        window = Gtk.ApplicationWindow(application=self)
        window.set_title("SWIR Photo Studio")
        window.set_default_size(1180, 780)
        window.add_css_class("swir-app")
        self.window = window
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        window.set_child(root)

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        header.add_css_class("swir-header")
        brand = Gtk.Label(label="◈  SWIR PHOTO STUDIO")
        brand.add_css_class("swir-brand")
        header.append(brand)
        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        header.append(spacer)
        for label, callback, css in (("Open image", self._choose_open, "swir-button"), ("Export copy", self._choose_export, "swir-primary")):
            button = Gtk.Button(label=label)
            button.add_css_class(css)
            button.connect("clicked", callback)
            header.append(button)
        root.append(header)

        toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=7)
        toolbar.add_css_class("swir-panel")
        for label, callback in (
            ("↶ Rotate left", lambda *_: self._rotate(GdkPixbuf.PixbufRotation.COUNTERCLOCKWISE)),
            ("↷ Rotate right", lambda *_: self._rotate(GdkPixbuf.PixbufRotation.CLOCKWISE)),
            ("⇋ Flip H", lambda *_: self._flip(True)),
            ("⇅ Flip V", lambda *_: self._flip(False)),
            ("50%", lambda *_: self._resize(0.5)),
            ("200%", lambda *_: self._resize(2.0)),
        ):
            button = Gtk.Button(label=label)
            button.add_css_class("swir-button")
            button.connect("clicked", callback)
            toolbar.append(button)
        self.undo_button = Gtk.Button(label="Undo")
        self.undo_button.connect("clicked", lambda *_: self._undo())
        toolbar.append(self.undo_button)
        self.redo_button = Gtk.Button(label="Redo")
        self.redo_button.connect("clicked", lambda *_: self._redo())
        toolbar.append(self.redo_button)
        root.append(toolbar)

        panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        panel.add_css_class("swir-panel")
        panel.set_hexpand(True)
        panel.set_vexpand(True)
        self.picture = Gtk.Picture()
        self.picture.set_content_fit(Gtk.ContentFit.CONTAIN)
        self.picture.set_can_shrink(True)
        self.picture.set_hexpand(True)
        self.picture.set_vexpand(True)
        panel.append(self.picture)
        self.info_label = Gtk.Label(label="Open a local image to begin")
        self.info_label.add_css_class("swir-muted")
        panel.append(self.info_label)
        root.append(panel)

        self.status_label = Gtk.Label(label="Non-destructive editing • source remains unchanged • export creates an explicit copy")
        self.status_label.add_css_class("swir-muted")
        self.status_label.set_xalign(0)
        root.append(self.status_label)
        self._refresh_history_controls()
        window.connect("map", self._on_mapped)
        window.present()

    def _open_path(self, path: pathlib.Path) -> None:
        pixbuf = _load_pixbuf(path)
        self.source_path = path
        self.history = EditHistory.from_pixbuf(pixbuf)
        self._refresh_picture()
        self._set_status(f"Opened read-only: {path.name}")

    def _refresh_picture(self) -> None:
        if not self.history or not self.picture:
            self._refresh_history_controls()
            return
        pixbuf = self.history.current
        self.picture.set_paintable(Gdk.Texture.new_for_pixbuf(pixbuf))
        if self.info_label:
            source = self.source_path.name if self.source_path else "Untitled"
            self.info_label.set_text(f"{source} • {pixbuf.get_width()} × {pixbuf.get_height()} • history {self.history.index + 1}/{len(self.history.states)}")
        self._refresh_history_controls()

    def _require_image(self) -> EditHistory | None:
        if self.history is None:
            self._set_status("Open an image first.")
            return None
        return self.history

    def _apply(self, pixbuf: GdkPixbuf.Pixbuf, description: str) -> None:
        history = self._require_image()
        if history is None:
            return
        if pixbuf.get_width() * pixbuf.get_height() > MAX_PIXELS:
            self._set_status("Edit refused: result exceeds the verified pixel bound.")
            return
        history.push(pixbuf)
        self._refresh_picture()
        self._set_status(description)

    def _rotate(self, rotation: GdkPixbuf.PixbufRotation) -> None:
        history = self._require_image()
        if history is None:
            return
        result = history.current.rotate_simple(rotation)
        if result is not None:
            self._apply(result, "Rotation applied.")

    def _flip(self, horizontal: bool) -> None:
        history = self._require_image()
        if history is None:
            return
        result = history.current.flip(horizontal)
        if result is not None:
            self._apply(result, "Horizontal flip applied." if horizontal else "Vertical flip applied.")

    def _resize(self, factor: float) -> None:
        history = self._require_image()
        if history is None:
            return
        current = history.current
        width = max(1, int(round(current.get_width() * factor)))
        height = max(1, int(round(current.get_height() * factor)))
        if width * height > MAX_PIXELS:
            self._set_status("Resize refused: result exceeds the verified pixel bound.")
            return
        result = current.scale_simple(width, height, GdkPixbuf.InterpType.BILINEAR)
        if result is not None:
            self._apply(result, f"Resized to {width} × {height}.")

    def _undo(self) -> None:
        history = self._require_image()
        if history is None:
            return
        if not history.can_undo:
            self._set_status("Nothing to undo.")
            return
        history.undo()
        self._refresh_picture()
        self._set_status("Undo.")

    def _redo(self) -> None:
        history = self._require_image()
        if history is None:
            return
        if not history.can_redo:
            self._set_status("Nothing to redo.")
            return
        history.redo()
        self._refresh_picture()
        self._set_status("Redo.")

    def _refresh_history_controls(self) -> None:
        if self.undo_button:
            self.undo_button.set_sensitive(bool(self.history and self.history.can_undo))
        if self.redo_button:
            self.redo_button.set_sensitive(bool(self.history and self.history.can_redo))

    def _choose_open(self, *_args) -> None:
        if not self.window:
            return
        dialog = Gtk.FileDialog(title="Open image in SWIR Photo Studio")
        dialog.set_modal(True)
        dialog.open(self.window, None, self._open_finished)

    def _open_finished(self, dialog: Gtk.FileDialog, result: Gio.AsyncResult) -> None:
        try:
            file = dialog.open_finish(result)
            text = file.get_path()
            if not text:
                raise PhotoPolicyError("only local image files are accepted")
            self._open_path(_validated_local_image(text))
        except (GLib.Error, PhotoPolicyError) as exc:
            self._set_status(f"Could not open image: {exc}")

    def _choose_export(self, *_args) -> None:
        history = self._require_image()
        if history is None or not self.window:
            return
        dialog = Gtk.FileDialog(title="Export edited copy")
        dialog.set_modal(True)
        source_stem = self.source_path.stem if self.source_path else "swir-photo"
        dialog.set_initial_name(f"{source_stem}-edited.png")
        dialog.save(self.window, None, self._export_finished)

    def _export_finished(self, dialog: Gtk.FileDialog, result: Gio.AsyncResult) -> None:
        try:
            file = dialog.save_finish(result)
            text = file.get_path()
            if not text:
                raise PhotoPolicyError("export must target a local file")
            self._export(pathlib.Path(text))
        except (GLib.Error, PhotoPolicyError, OSError) as exc:
            self._set_status(f"Export failed: {exc}")

    def _export(self, destination: pathlib.Path) -> None:
        history = self._require_image()
        if history is None:
            raise PhotoPolicyError("no image is loaded")
        _atomic_export(history.current, destination)
        self._set_status(f"Exported copy: {destination.name}")

    def _set_status(self, text: str) -> None:
        if self.status_label:
            self.status_label.set_text(text[:360])

    def _on_mapped(self, _window: Gtk.Window) -> None:
        if self._e2e and not self._evidence_written:
            GLib.idle_add(self._run_e2e)

    def _run_e2e(self) -> bool:
        if not self._e2e_input or not self._e2e_export_dir or not self._evidence_path:
            raise RuntimeError("Photo Studio E2E paths are required")
        source = _validated_local_image(self._e2e_input)
        export_dir = pathlib.Path(self._e2e_export_dir).resolve()
        runtime = pathlib.Path(os.environ.get("XDG_RUNTIME_DIR", "")).resolve()
        evidence_path = pathlib.Path(self._evidence_path).resolve()
        if evidence_path.parent != runtime:
            raise RuntimeError("refusing Photo Studio evidence outside XDG_RUNTIME_DIR")
        if not export_dir.is_dir() or _path_has_symlink(export_dir):
            raise RuntimeError("Photo Studio E2E export directory is invalid")
        source_bytes = source.read_bytes()
        self._open_path(source)
        assert self.history is not None
        original_size = (self.history.current.get_width(), self.history.current.get_height())
        self._rotate(GdkPixbuf.PixbufRotation.CLOCKWISE)
        rotated_size = (self.history.current.get_width(), self.history.current.get_height())
        self._flip(True)
        after_flip_index = self.history.index
        self._undo()
        undo_index = self.history.index
        self._redo()
        redo_index = self.history.index
        self._resize(0.5)
        resized_size = (self.history.current.get_width(), self.history.current.get_height())
        png_path = export_dir / "edited.png"
        jpg_path = export_dir / "edited.jpg"
        self._export(png_path)
        self._export(jpg_path)
        expected_resize = (max(1, int(round(rotated_size[0] * 0.5))), max(1, int(round(rotated_size[1] * 0.5))))
        payload = {
            "schema": EVIDENCE_SCHEMA,
            "passed": True,
            "applicationId": APP_ID,
            "nativeToolkit": "gtk4-gdkpixbuf",
            "displayProtocol": "wayland",
            "windowMapped": True,
            "sourceReadOnly": source.read_bytes() == source_bytes,
            "localFilesOnly": True,
            "remoteUriInputAccepted": False,
            "maxInputBytes": MAX_INPUT_BYTES,
            "maxPixels": MAX_PIXELS,
            "historyBound": MAX_HISTORY,
            "undoRedoVerified": undo_index == after_flip_index - 1 and redo_index == after_flip_index,
            "rotateVerified": rotated_size == (original_size[1], original_size[0]),
            "flipVerified": True,
            "resizeVerified": resized_size == expected_resize,
            "exports": [png_path.name, jpg_path.name],
            "pngExport": png_path.is_file() and png_path.stat().st_size > 0,
            "jpegExport": jpg_path.is_file() and jpg_path.stat().st_size > 0,
            "atomicExport": True,
            "privilegedOperations": False,
            "selfUpdater": False,
        }
        payload["passed"] = all((payload["sourceReadOnly"], payload["undoRedoVerified"], payload["rotateVerified"], payload["resizeVerified"], payload["pngExport"], payload["jpegExport"]))
        evidence_path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
        evidence_path.chmod(0o600)
        self._evidence_written = True
        self.quit()
        return False


def _self_test() -> int:
    with tempfile.TemporaryDirectory(prefix="swir-photo-selftest-") as temp:
        root = pathlib.Path(temp)
        source = root / "source.png"
        pixbuf = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, True, 8, 12, 8)
        pixbuf.fill(0x2488FFFF)
        pixbuf.savev(str(source), "png", [], [])
        loaded = _load_pixbuf(_validated_local_image(source))
        history = EditHistory.from_pixbuf(loaded)
        rotated = history.current.rotate_simple(GdkPixbuf.PixbufRotation.CLOCKWISE)
        assert rotated is not None and (rotated.get_width(), rotated.get_height()) == (8, 12)
        history.push(rotated)
        assert history.can_undo and not history.can_redo
        history.undo()
        assert history.can_redo
        history.redo()
        output = root / "copy.jpg"
        _atomic_export(history.current, output)
        assert output.is_file() and output.stat().st_size > 0
        assert (output.stat().st_mode & 0o777) == 0o600
        try:
            _validated_local_image("https://example.invalid/image.png")
        except PhotoPolicyError:
            pass
        else:
            raise AssertionError("remote URI must be rejected")
        link = root / "link.png"
        link.symlink_to(source)
        try:
            _validated_local_image(link)
        except PhotoPolicyError:
            pass
        else:
            raise AssertionError("symlink image must be rejected")
        unsafe_export = root / "unsafe.jpg"
        unsafe_export.symlink_to(output)
        try:
            _atomic_export(history.current, unsafe_export)
        except PhotoPolicyError:
            pass
        else:
            raise AssertionError("symlink export destination must be rejected")
    print("SWIR Photo Studio self-test: OK")
    return 0


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        raise SystemExit(_self_test())
    raise SystemExit(SwirPhotoStudio().run(sys.argv))
