#!/usr/bin/env python3
"""SWIR Photo Studio — native GTK4 image viewer/editor for System Edition.

The application is unprivileged and deliberately non-destructive: source images
are opened read-only, edits stay in memory with bounded undo/redo history, and
users export an explicit copy in PNG/JPEG/WebP. There is no package mutation,
self-updater, sudo/pkexec shortcut, remote-URI input path, or external image
processor.

The verified 0.3 editing baseline stays inside distro-managed GTK4/GdkPixbuf and
adds bounded rectangular crop, exposure/brightness/contrast/saturation, filters,
bitmap text and line annotation while preserving alpha and the original source.
"""

from __future__ import annotations

import json
import math
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
EVIDENCE_SCHEMA: Final = "swir.native-photo-studio-runtime-evidence/0.3"
MAX_INPUT_BYTES: Final = 64 * 1024 * 1024
MAX_PIXELS: Final = 40_000_000
MAX_HISTORY: Final = 24
MAX_PATH_BYTES: Final = 4096
MAX_ANNOTATION_CHARS: Final = 64
MAX_TEXT_SCALE: Final = 6
MAX_LINE_WIDTH: Final = 12
ANNOTATION_COLOR: Final = (98, 229, 255)
SUPPORTED_INPUT_SUFFIXES: Final = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff"}
EXPORT_FORMATS: Final = {
    ".png": ("png", [], []),
    ".jpg": ("jpeg", ["quality"], ["92"]),
    ".jpeg": ("jpeg", ["quality"], ["92"]),
    ".webp": ("webp", ["quality"], ["90"]),
}

FONT_5X7: Final = {
    "A": ("01110", "10001", "10001", "11111", "10001", "10001", "10001"),
    "B": ("11110", "10001", "10001", "11110", "10001", "10001", "11110"),
    "C": ("01111", "10000", "10000", "10000", "10000", "10000", "01111"),
    "D": ("11110", "10001", "10001", "10001", "10001", "10001", "11110"),
    "E": ("11111", "10000", "10000", "11110", "10000", "10000", "11111"),
    "F": ("11111", "10000", "10000", "11110", "10000", "10000", "10000"),
    "G": ("01111", "10000", "10000", "10111", "10001", "10001", "01111"),
    "H": ("10001", "10001", "10001", "11111", "10001", "10001", "10001"),
    "I": ("11111", "00100", "00100", "00100", "00100", "00100", "11111"),
    "J": ("00111", "00010", "00010", "00010", "10010", "10010", "01100"),
    "K": ("10001", "10010", "10100", "11000", "10100", "10010", "10001"),
    "L": ("10000", "10000", "10000", "10000", "10000", "10000", "11111"),
    "M": ("10001", "11011", "10101", "10101", "10001", "10001", "10001"),
    "N": ("10001", "11001", "10101", "10011", "10001", "10001", "10001"),
    "O": ("01110", "10001", "10001", "10001", "10001", "10001", "01110"),
    "P": ("11110", "10001", "10001", "11110", "10000", "10000", "10000"),
    "Q": ("01110", "10001", "10001", "10001", "10101", "10010", "01101"),
    "R": ("11110", "10001", "10001", "11110", "10100", "10010", "10001"),
    "S": ("01111", "10000", "10000", "01110", "00001", "00001", "11110"),
    "T": ("11111", "00100", "00100", "00100", "00100", "00100", "00100"),
    "U": ("10001", "10001", "10001", "10001", "10001", "10001", "01110"),
    "V": ("10001", "10001", "10001", "10001", "10001", "01010", "00100"),
    "W": ("10001", "10001", "10001", "10101", "10101", "10101", "01010"),
    "X": ("10001", "10001", "01010", "00100", "01010", "10001", "10001"),
    "Y": ("10001", "10001", "01010", "00100", "00100", "00100", "00100"),
    "Z": ("11111", "00001", "00010", "00100", "01000", "10000", "11111"),
    "0": ("01110", "10001", "10011", "10101", "11001", "10001", "01110"),
    "1": ("00100", "01100", "00100", "00100", "00100", "00100", "01110"),
    "2": ("01110", "10001", "00001", "00010", "00100", "01000", "11111"),
    "3": ("11110", "00001", "00001", "01110", "00001", "00001", "11110"),
    "4": ("00010", "00110", "01010", "10010", "11111", "00010", "00010"),
    "5": ("11111", "10000", "10000", "11110", "00001", "00001", "11110"),
    "6": ("01110", "10000", "10000", "11110", "10001", "10001", "01110"),
    "7": ("11111", "00001", "00010", "00100", "01000", "01000", "01000"),
    "8": ("01110", "10001", "10001", "01110", "10001", "10001", "01110"),
    "9": ("01110", "10001", "10001", "01111", "00001", "00001", "01110"),
    " ": ("00000",) * 7,
    "-": ("00000", "00000", "00000", "11111", "00000", "00000", "00000"),
    ".": ("00000", "00000", "00000", "00000", "00000", "00110", "00110"),
    ":": ("00000", "00110", "00110", "00000", "00110", "00110", "00000"),
    "/": ("00001", "00010", "00010", "00100", "01000", "01000", "10000"),
    "?": ("01110", "10001", "00001", "00010", "00100", "00000", "00100"),
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
entry, spinbutton { min-width: 74px; }
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


def _clamp_channel(value: float) -> int:
    return max(0, min(255, int(round(value))))


def _pixbuf_from_tight_bytes(data: bytes | bytearray, width: int, height: int, channels: int, has_alpha: bool) -> GdkPixbuf.Pixbuf:
    if width <= 0 or height <= 0 or width * height > MAX_PIXELS:
        raise PhotoPolicyError("edit result dimensions exceed the verified bound")
    expected = width * height * channels
    if len(data) != expected:
        raise PhotoPolicyError("internal pixel buffer size mismatch")
    return GdkPixbuf.Pixbuf.new_from_bytes(GLib.Bytes.new(bytes(data)), GdkPixbuf.Colorspace.RGB, has_alpha, 8, width, height, width * channels)


def _tight_pixel_copy(pixbuf: GdkPixbuf.Pixbuf) -> tuple[bytearray, int, int, int, bool]:
    width, height = pixbuf.get_width(), pixbuf.get_height()
    channels = pixbuf.get_n_channels()
    has_alpha = pixbuf.get_has_alpha()
    if channels not in (3, 4) or channels != (4 if has_alpha else 3):
        raise PhotoPolicyError("unsupported decoded pixel layout")
    source = bytes(pixbuf.get_pixels())
    stride = pixbuf.get_rowstride()
    packed = bytearray(width * height * channels)
    for y in range(height):
        start = y * stride
        packed[y * width * channels:(y + 1) * width * channels] = source[start:start + width * channels]
    return packed, width, height, channels, has_alpha


def _rgb_at(pixbuf: GdkPixbuf.Pixbuf, x: int, y: int) -> tuple[int, int, int]:
    if x < 0 or y < 0 or x >= pixbuf.get_width() or y >= pixbuf.get_height():
        raise PhotoPolicyError("pixel coordinate is outside image bounds")
    channels = pixbuf.get_n_channels()
    offset = y * pixbuf.get_rowstride() + x * channels
    pixels = bytes(pixbuf.get_pixels())
    return pixels[offset], pixels[offset + 1], pixels[offset + 2]


def _transform_pixels(pixbuf: GdkPixbuf.Pixbuf, *, exposure_stops: float = 0.0, brightness: float = 0.0, contrast: float = 0.0, saturation: float = 0.0, grayscale: bool = False, sepia: bool = False) -> GdkPixbuf.Pixbuf:
    if not -2.0 <= exposure_stops <= 2.0:
        raise PhotoPolicyError("exposure adjustment is outside the verified range")
    if not -1.0 <= brightness <= 1.0:
        raise PhotoPolicyError("brightness adjustment is outside the verified range")
    if not -0.9 <= contrast <= 2.0:
        raise PhotoPolicyError("contrast adjustment is outside the verified range")
    if not -1.0 <= saturation <= 2.0:
        raise PhotoPolicyError("saturation adjustment is outside the verified range")
    width, height = pixbuf.get_width(), pixbuf.get_height()
    channels, has_alpha = pixbuf.get_n_channels(), pixbuf.get_has_alpha()
    if channels not in (3, 4) or channels != (4 if has_alpha else 3):
        raise PhotoPolicyError("unsupported decoded pixel layout")
    source, source_stride = bytes(pixbuf.get_pixels()), pixbuf.get_rowstride()
    output = bytearray(width * height * channels)
    exposure_factor, contrast_factor, saturation_factor, brightness_delta = math.pow(2.0, exposure_stops), 1.0 + contrast, 1.0 + saturation, brightness * 255.0
    for y in range(height):
        for x in range(width):
            src, dst = y * source_stride + x * channels, (y * width + x) * channels
            r, g, b = float(source[src]), float(source[src + 1]), float(source[src + 2])
            r *= exposure_factor; g *= exposure_factor; b *= exposure_factor
            r = (r - 127.5) * contrast_factor + 127.5 + brightness_delta
            g = (g - 127.5) * contrast_factor + 127.5 + brightness_delta
            b = (b - 127.5) * contrast_factor + 127.5 + brightness_delta
            luminance = 0.2126 * r + 0.7152 * g + 0.0722 * b
            r = luminance + (r - luminance) * saturation_factor; g = luminance + (g - luminance) * saturation_factor; b = luminance + (b - luminance) * saturation_factor
            if grayscale:
                gray = _clamp_channel(0.2126 * r + 0.7152 * g + 0.0722 * b); r = g = b = float(gray)
            elif sepia:
                r, g, b = 0.393 * r + 0.769 * g + 0.189 * b, 0.349 * r + 0.686 * g + 0.168 * b, 0.272 * r + 0.534 * g + 0.131 * b
            output[dst], output[dst + 1], output[dst + 2] = _clamp_channel(r), _clamp_channel(g), _clamp_channel(b)
            if has_alpha:
                output[dst + 3] = source[src + 3]
    return _pixbuf_from_tight_bytes(output, width, height, channels, has_alpha)


def _crop_pixbuf(pixbuf: GdkPixbuf.Pixbuf, x: int, y: int, width: int, height: int) -> GdkPixbuf.Pixbuf:
    full_width, full_height = pixbuf.get_width(), pixbuf.get_height()
    if width <= 0 or height <= 0 or x < 0 or y < 0:
        raise PhotoPolicyError("crop rectangle must have positive dimensions")
    if x + width > full_width or y + height > full_height:
        raise PhotoPolicyError("crop rectangle exceeds the image bounds")
    if width * height > MAX_PIXELS:
        raise PhotoPolicyError("crop result exceeds the verified pixel bound")
    return pixbuf.new_subpixbuf(x, y, width, height).copy()


def _center_crop(pixbuf: GdkPixbuf.Pixbuf, fraction: float = 0.8) -> GdkPixbuf.Pixbuf:
    if not 0.1 <= fraction <= 1.0:
        raise PhotoPolicyError("center-crop fraction is outside the verified range")
    full_width, full_height = pixbuf.get_width(), pixbuf.get_height()
    width, height = max(1, int(round(full_width * fraction))), max(1, int(round(full_height * fraction)))
    return _crop_pixbuf(pixbuf, (full_width - width) // 2, (full_height - height) // 2, width, height)


def _validated_color(color: tuple[int, int, int]) -> tuple[int, int, int]:
    if not isinstance(color, tuple) or len(color) != 3 or any(not isinstance(v, int) or not 0 <= v <= 255 for v in color):
        raise PhotoPolicyError("annotation color must be a bounded RGB tuple")
    return color


def _draw_line(pixbuf: GdkPixbuf.Pixbuf, x0: int, y0: int, x1: int, y1: int, *, width: int = 3, color: tuple[int, int, int] = ANNOTATION_COLOR) -> GdkPixbuf.Pixbuf:
    packed, image_width, image_height, channels, has_alpha = _tight_pixel_copy(pixbuf)
    if not 1 <= width <= MAX_LINE_WIDTH:
        raise PhotoPolicyError("annotation line width is outside the verified range")
    for value, limit, name in ((x0, image_width, "x0"), (x1, image_width, "x1"), (y0, image_height, "y0"), (y1, image_height, "y1")):
        if not isinstance(value, int) or value < 0 or value >= limit:
            raise PhotoPolicyError(f"annotation coordinate {name} is outside image bounds")
    r, g, b = _validated_color(color)
    radius_before, radius_after = (width - 1) // 2, width // 2
    def paint(cx: int, cy: int) -> None:
        for py in range(max(0, cy - radius_before), min(image_height, cy + radius_after + 1)):
            for px in range(max(0, cx - radius_before), min(image_width, cx + radius_after + 1)):
                pos = (py * image_width + px) * channels
                packed[pos:pos + 3] = bytes((r, g, b))
    dx, sx, dy, sy = abs(x1 - x0), 1 if x0 < x1 else -1, -abs(y1 - y0), 1 if y0 < y1 else -1
    error, x, y = dx + dy, x0, y0
    while True:
        paint(x, y)
        if x == x1 and y == y1:
            break
        twice = 2 * error
        if twice >= dy:
            error += dy; x += sx
        if twice <= dx:
            error += dx; y += sy
    return _pixbuf_from_tight_bytes(packed, image_width, image_height, channels, has_alpha)


def _normalize_annotation_text(raw: str) -> str:
    if not isinstance(raw, str):
        raise PhotoPolicyError("annotation text must be a string")
    text = raw.strip().upper()
    if not text or len(text) > MAX_ANNOTATION_CHARS:
        raise PhotoPolicyError("annotation text length is outside the verified bound")
    if any(ord(char) < 32 or ord(char) > 126 for char in text):
        raise PhotoPolicyError("annotation text contains unsupported control/non-ASCII characters")
    unsupported = sorted({char for char in text if char not in FONT_5X7})
    if unsupported:
        raise PhotoPolicyError(f"annotation text contains unsupported characters: {''.join(unsupported)}")
    return text


def _annotate_text(pixbuf: GdkPixbuf.Pixbuf, text: str, x: int, y: int, *, scale: int = 2, color: tuple[int, int, int] = ANNOTATION_COLOR) -> GdkPixbuf.Pixbuf:
    normalized = _normalize_annotation_text(text)
    packed, image_width, image_height, channels, has_alpha = _tight_pixel_copy(pixbuf)
    if not isinstance(scale, int) or not 1 <= scale <= MAX_TEXT_SCALE:
        raise PhotoPolicyError("annotation text scale is outside the verified range")
    if not isinstance(x, int) or not isinstance(y, int) or x < 0 or y < 0:
        raise PhotoPolicyError("annotation text origin is invalid")
    glyph_width, glyph_height, spacing = 5 * scale, 7 * scale, scale
    required_width = len(normalized) * glyph_width + (len(normalized) - 1) * spacing
    if x + required_width > image_width or y + glyph_height > image_height:
        raise PhotoPolicyError("annotation text does not fit inside image bounds")
    r, g, b = _validated_color(color)
    for char_index, char in enumerate(normalized):
        origin_x = x + char_index * (glyph_width + spacing)
        for row_index, row in enumerate(FONT_5X7[char]):
            for column_index, bit in enumerate(row):
                if bit != "1":
                    continue
                base_x, base_y = origin_x + column_index * scale, y + row_index * scale
                for py in range(base_y, base_y + scale):
                    for px in range(base_x, base_x + scale):
                        pos = (py * image_width + px) * channels
                        packed[pos:pos + 3] = bytes((r, g, b))
    return _pixbuf_from_tight_bytes(packed, image_width, image_height, channels, has_alpha)


def _first_rgb(pixbuf: GdkPixbuf.Pixbuf) -> tuple[int, int, int]:
    return _rgb_at(pixbuf, 0, 0)


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
        del self.states[self.index + 1:]
        self.states.append(pixbuf.copy())
        if len(self.states) > MAX_HISTORY:
            del self.states[:len(self.states) - MAX_HISTORY]
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
        self.window = self.picture = self.status_label = self.info_label = None
        self.undo_button = self.redo_button = None
        self.history: EditHistory | None = None
        self.source_path: pathlib.Path | None = None
        self.crop_x = self.crop_y = self.crop_w = self.crop_h = None
        self.text_entry = self.text_x = self.text_y = self.text_scale = None
        self.line_x0 = self.line_y0 = self.line_x1 = self.line_y1 = self.line_width = None
        self._e2e = os.environ.get("SWIR_APP_E2E") == "1"
        self._evidence_path = os.environ.get("SWIR_APP_EVIDENCE_PATH", "")
        self._e2e_input = os.environ.get("SWIR_PHOTO_E2E_IMAGE", "")
        self._e2e_export_dir = os.environ.get("SWIR_PHOTO_E2E_EXPORT_DIR", "")
        self._evidence_written = False

    @staticmethod
    def _spin(minimum: int, maximum: int, value: int = 0) -> Gtk.SpinButton:
        spin = Gtk.SpinButton.new_with_range(minimum, maximum, 1); spin.set_value(value); spin.set_numeric(True); return spin

    @staticmethod
    def _label(text: str) -> Gtk.Label:
        label = Gtk.Label(label=text); label.add_css_class("swir-muted"); return label

    def do_startup(self) -> None:
        Gtk.Application.do_startup(self)
        provider = Gtk.CssProvider(); provider.load_from_data(CSS)
        display = Gdk.Display.get_default()
        if display is None:
            raise RuntimeError("SWIR Photo Studio requires an active graphical display")
        Gtk.StyleContext.add_provider_for_display(display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        for name, accelerator, callback in (("open", "<Primary>O", self._choose_open), ("export", "<Primary><Shift>S", self._choose_export), ("undo", "<Primary>Z", lambda *_: self._undo()), ("redo", "<Primary><Shift>Z", lambda *_: self._redo())):
            action = Gio.SimpleAction.new(name, None); action.connect("activate", callback); self.add_action(action); self.set_accels_for_action(f"app.{name}", [accelerator])

    def do_command_line(self, command_line: Gio.ApplicationCommandLine) -> int:
        args, requested, index = command_line.get_arguments()[1:], None, 0
        while index < len(args):
            if args[index] == "--open" and index + 1 < len(args):
                try:
                    requested = _validated_local_image(args[index + 1])
                except PhotoPolicyError as exc:
                    print(f"SWIR Photo Studio refused image: {exc}", file=sys.stderr); return 64
                index += 2; continue
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
                self._set_status("Only local image files are accepted."); return
            try:
                self._open_path(_validated_local_image(text))
            except PhotoPolicyError as exc:
                self._set_status(str(exc))
            break

    def do_activate(self) -> None:
        if self.window is not None:
            self.window.present(); return
        window = Gtk.ApplicationWindow(application=self); window.set_title("SWIR Photo Studio"); window.set_default_size(1260, 900); window.add_css_class("swir-app"); self.window = window
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6); window.set_child(root)
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8); header.add_css_class("swir-header")
        brand = Gtk.Label(label="◈  SWIR PHOTO STUDIO"); brand.add_css_class("swir-brand"); header.append(brand)
        spacer = Gtk.Box(); spacer.set_hexpand(True); header.append(spacer)
        for label, callback, css in (("Open image", self._choose_open, "swir-button"), ("Export copy", self._choose_export, "swir-primary")):
            button = Gtk.Button(label=label); button.add_css_class(css); button.connect("clicked", callback); header.append(button)
        root.append(header)
        basic = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=7); basic.add_css_class("swir-panel")
        for label, callback in (("↶ Rotate", lambda *_: self._rotate(GdkPixbuf.PixbufRotation.COUNTERCLOCKWISE)), ("↷ Rotate", lambda *_: self._rotate(GdkPixbuf.PixbufRotation.CLOCKWISE)), ("⇋ Flip H", lambda *_: self._flip(True)), ("⇅ Flip V", lambda *_: self._flip(False)), ("Crop 80%", lambda *_: self._crop_center()), ("50%", lambda *_: self._resize(0.5)), ("200%", lambda *_: self._resize(2.0))):
            button = Gtk.Button(label=label); button.add_css_class("swir-button"); button.connect("clicked", callback); basic.append(button)
        self.undo_button = Gtk.Button(label="Undo"); self.undo_button.connect("clicked", lambda *_: self._undo()); basic.append(self.undo_button)
        self.redo_button = Gtk.Button(label="Redo"); self.redo_button.connect("clicked", lambda *_: self._redo()); basic.append(self.redo_button); root.append(basic)
        crop = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6); crop.add_css_class("swir-panel")
        crop.append(self._label("Crop x")); self.crop_x = self._spin(0, 1); crop.append(self.crop_x); crop.append(self._label("y")); self.crop_y = self._spin(0, 1); crop.append(self.crop_y)
        crop.append(self._label("w")); self.crop_w = self._spin(1, 1, 1); crop.append(self.crop_w); crop.append(self._label("h")); self.crop_h = self._spin(1, 1, 1); crop.append(self.crop_h)
        crop_button = Gtk.Button(label="Apply crop"); crop_button.add_css_class("swir-button"); crop_button.connect("clicked", lambda *_: self._crop_from_controls()); crop.append(crop_button); root.append(crop)
        color = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=7); color.add_css_class("swir-panel")
        for label, callback in (("Exposure −", lambda *_: self._adjust(exposure_stops=-0.25, description="Exposure −0.25 EV.")), ("Exposure +", lambda *_: self._adjust(exposure_stops=0.25, description="Exposure +0.25 EV.")), ("Brightness −", lambda *_: self._adjust(brightness=-0.08, description="Brightness reduced.")), ("Brightness +", lambda *_: self._adjust(brightness=0.08, description="Brightness increased.")), ("Contrast −", lambda *_: self._adjust(contrast=-0.10, description="Contrast reduced.")), ("Contrast +", lambda *_: self._adjust(contrast=0.10, description="Contrast increased.")), ("Saturation −", lambda *_: self._adjust(saturation=-0.12, description="Saturation reduced.")), ("Saturation +", lambda *_: self._adjust(saturation=0.12, description="Saturation increased.")), ("B&W", lambda *_: self._adjust(grayscale=True, description="Grayscale filter applied.")), ("Sepia", lambda *_: self._adjust(sepia=True, description="Sepia filter applied."))):
            button = Gtk.Button(label=label); button.add_css_class("swir-button"); button.connect("clicked", callback); color.append(button)
        color_scroll = Gtk.ScrolledWindow(); color_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.NEVER); color_scroll.set_child(color); root.append(color_scroll)
        annotate = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6); annotate.add_css_class("swir-panel")
        annotate.append(self._label("Text")); self.text_entry = Gtk.Entry(); self.text_entry.set_placeholder_text("SWIR TEXT"); self.text_entry.set_max_length(MAX_ANNOTATION_CHARS); annotate.append(self.text_entry)
        annotate.append(self._label("x")); self.text_x = self._spin(0, 1); annotate.append(self.text_x); annotate.append(self._label("y")); self.text_y = self._spin(0, 1); annotate.append(self.text_y); annotate.append(self._label("scale")); self.text_scale = self._spin(1, MAX_TEXT_SCALE, 2); annotate.append(self.text_scale)
        text_button = Gtk.Button(label="Add text"); text_button.add_css_class("swir-button"); text_button.connect("clicked", lambda *_: self._annotate_from_controls()); annotate.append(text_button); root.append(annotate)
        line = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6); line.add_css_class("swir-panel")
        for label, attr in (("x0", "line_x0"), ("y0", "line_y0"), ("x1", "line_x1"), ("y1", "line_y1")):
            line.append(self._label(label)); spin = self._spin(0, 1); setattr(self, attr, spin); line.append(spin)
        line.append(self._label("width")); self.line_width = self._spin(1, MAX_LINE_WIDTH, 3); line.append(self.line_width)
        line_button = Gtk.Button(label="Draw cyan line"); line_button.add_css_class("swir-button"); line_button.connect("clicked", lambda *_: self._draw_line_from_controls()); line.append(line_button); root.append(line)
        panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8); panel.add_css_class("swir-panel"); panel.set_hexpand(True); panel.set_vexpand(True)
        self.picture = Gtk.Picture(); self.picture.set_content_fit(Gtk.ContentFit.CONTAIN); self.picture.set_can_shrink(True); self.picture.set_hexpand(True); self.picture.set_vexpand(True); panel.append(self.picture)
        self.info_label = Gtk.Label(label="Open a local image to begin"); self.info_label.add_css_class("swir-muted"); panel.append(self.info_label); root.append(panel)
        self.status_label = Gtk.Label(label="Non-destructive editing • source unchanged • explicit export copy"); self.status_label.add_css_class("swir-muted"); self.status_label.set_xalign(0); root.append(self.status_label)
        self._refresh_history_controls(); self._sync_geometry_controls(); window.connect("map", self._on_mapped); window.present()

    def _open_path(self, path: pathlib.Path) -> None:
        self.source_path = path; self.history = EditHistory.from_pixbuf(_load_pixbuf(path)); self._refresh_picture(); self._set_status(f"Opened read-only: {path.name}")

    def _refresh_picture(self) -> None:
        if not self.history or not self.picture:
            self._refresh_history_controls(); self._sync_geometry_controls(); return
        pixbuf = self.history.current; self.picture.set_paintable(Gdk.Texture.new_for_pixbuf(pixbuf))
        if self.info_label:
            source = self.source_path.name if self.source_path else "Untitled"; self.info_label.set_text(f"{source} • {pixbuf.get_width()} × {pixbuf.get_height()} • history {self.history.index + 1}/{len(self.history.states)}")
        self._refresh_history_controls(); self._sync_geometry_controls()

    def _sync_geometry_controls(self) -> None:
        width = self.history.current.get_width() if self.history else 1; height = self.history.current.get_height() if self.history else 1
        for spin, maximum in ((self.crop_x, max(0, width - 1)), (self.text_x, max(0, width - 1)), (self.line_x0, max(0, width - 1)), (self.line_x1, max(0, width - 1))):
            if spin: spin.set_range(0, maximum); spin.set_value(0)
        for spin, maximum in ((self.crop_y, max(0, height - 1)), (self.text_y, max(0, height - 1)), (self.line_y0, max(0, height - 1)), (self.line_y1, max(0, height - 1))):
            if spin: spin.set_range(0, maximum); spin.set_value(0)
        if self.crop_w: self.crop_w.set_range(1, width); self.crop_w.set_value(width)
        if self.crop_h: self.crop_h.set_range(1, height); self.crop_h.set_value(height)
        if self.line_x1: self.line_x1.set_value(max(0, width - 1))
        if self.line_y1: self.line_y1.set_value(max(0, height - 1))

    def _require_image(self) -> EditHistory | None:
        if self.history is None:
            self._set_status("Open an image first."); return None
        return self.history

    def _apply(self, pixbuf: GdkPixbuf.Pixbuf, description: str) -> None:
        history = self._require_image()
        if history is None: return
        if pixbuf.get_width() * pixbuf.get_height() > MAX_PIXELS:
            self._set_status("Edit refused: result exceeds the verified pixel bound."); return
        history.push(pixbuf); self._refresh_picture(); self._set_status(description)

    def _rotate(self, rotation: GdkPixbuf.PixbufRotation) -> None:
        history = self._require_image()
        if history is None: return
        result = history.current.rotate_simple(rotation)
        if result is not None: self._apply(result, "Rotation applied.")

    def _flip(self, horizontal: bool) -> None:
        history = self._require_image()
        if history is None: return
        result = history.current.flip(horizontal)
        if result is not None: self._apply(result, "Horizontal flip applied." if horizontal else "Vertical flip applied.")

    def _resize(self, factor: float) -> None:
        history = self._require_image()
        if history is None: return
        current = history.current; width, height = max(1, int(round(current.get_width() * factor))), max(1, int(round(current.get_height() * factor)))
        if width * height > MAX_PIXELS:
            self._set_status("Resize refused: result exceeds the verified pixel bound."); return
        result = current.scale_simple(width, height, GdkPixbuf.InterpType.BILINEAR)
        if result is not None: self._apply(result, f"Resized to {width} × {height}.")

    def _crop_center(self) -> None:
        history = self._require_image()
        if history is None: return
        try: result = _center_crop(history.current, 0.8)
        except PhotoPolicyError as exc: self._set_status(f"Crop refused: {exc}"); return
        self._apply(result, f"Center crop applied: {result.get_width()} × {result.get_height()}.")

    def _crop_rect(self, x: int, y: int, width: int, height: int) -> None:
        history = self._require_image()
        if history is None: return
        try: result = _crop_pixbuf(history.current, x, y, width, height)
        except PhotoPolicyError as exc: self._set_status(f"Crop refused: {exc}"); return
        self._apply(result, f"Crop applied: x={x}, y={y}, {width} × {height}.")

    def _crop_from_controls(self) -> None:
        if not all((self.crop_x, self.crop_y, self.crop_w, self.crop_h)): return
        self._crop_rect(self.crop_x.get_value_as_int(), self.crop_y.get_value_as_int(), self.crop_w.get_value_as_int(), self.crop_h.get_value_as_int())

    def _adjust(self, *, description: str, **kwargs) -> None:
        history = self._require_image()
        if history is None: return
        try: result = _transform_pixels(history.current, **kwargs)
        except PhotoPolicyError as exc: self._set_status(f"Adjustment refused: {exc}"); return
        self._apply(result, description)

    def _annotate_current(self, text: str, x: int, y: int, scale: int) -> None:
        history = self._require_image()
        if history is None: return
        try: result = _annotate_text(history.current, text, x, y, scale=scale)
        except PhotoPolicyError as exc: self._set_status(f"Text refused: {exc}"); return
        self._apply(result, f"Text annotation added at {x},{y}.")

    def _annotate_from_controls(self) -> None:
        if not all((self.text_entry, self.text_x, self.text_y, self.text_scale)): return
        self._annotate_current(self.text_entry.get_text(), self.text_x.get_value_as_int(), self.text_y.get_value_as_int(), self.text_scale.get_value_as_int())

    def _draw_current_line(self, x0: int, y0: int, x1: int, y1: int, width: int) -> None:
        history = self._require_image()
        if history is None: return
        try: result = _draw_line(history.current, x0, y0, x1, y1, width=width)
        except PhotoPolicyError as exc: self._set_status(f"Drawing refused: {exc}"); return
        self._apply(result, f"Line annotation added: ({x0},{y0}) → ({x1},{y1}).")

    def _draw_line_from_controls(self) -> None:
        controls = (self.line_x0, self.line_y0, self.line_x1, self.line_y1, self.line_width)
        if not all(controls): return
        self._draw_current_line(*(spin.get_value_as_int() for spin in controls))

    def _undo(self) -> None:
        history = self._require_image()
        if history is None: return
        if not history.can_undo: self._set_status("Nothing to undo."); return
        history.undo(); self._refresh_picture(); self._set_status("Undo.")

    def _redo(self) -> None:
        history = self._require_image()
        if history is None: return
        if not history.can_redo: self._set_status("Nothing to redo."); return
        history.redo(); self._refresh_picture(); self._set_status("Redo.")

    def _refresh_history_controls(self) -> None:
        if self.undo_button: self.undo_button.set_sensitive(bool(self.history and self.history.can_undo))
        if self.redo_button: self.redo_button.set_sensitive(bool(self.history and self.history.can_redo))

    def _choose_open(self, *_args) -> None:
        if not self.window: return
        dialog = Gtk.FileDialog(title="Open image in SWIR Photo Studio"); dialog.set_modal(True); dialog.open(self.window, None, self._open_finished)

    def _open_finished(self, dialog: Gtk.FileDialog, result: Gio.AsyncResult) -> None:
        try:
            file = dialog.open_finish(result); text = file.get_path()
            if not text: raise PhotoPolicyError("only local image files are accepted")
            self._open_path(_validated_local_image(text))
        except (GLib.Error, PhotoPolicyError) as exc: self._set_status(f"Could not open image: {exc}")

    def _choose_export(self, *_args) -> None:
        history = self._require_image()
        if history is None or not self.window: return
        dialog = Gtk.FileDialog(title="Export edited copy"); dialog.set_modal(True); source_stem = self.source_path.stem if self.source_path else "swir-photo"; dialog.set_initial_name(f"{source_stem}-edited.png"); dialog.save(self.window, None, self._export_finished)

    def _export_finished(self, dialog: Gtk.FileDialog, result: Gio.AsyncResult) -> None:
        try:
            file = dialog.save_finish(result); text = file.get_path()
            if not text: raise PhotoPolicyError("export must target a local file")
            self._export(pathlib.Path(text))
        except (GLib.Error, PhotoPolicyError, OSError) as exc: self._set_status(f"Export failed: {exc}")

    def _export(self, destination: pathlib.Path) -> None:
        history = self._require_image()
        if history is None: raise PhotoPolicyError("no image is loaded")
        _atomic_export(history.current, destination); self._set_status(f"Exported copy: {destination.name}")

    def _set_status(self, text: str) -> None:
        if self.status_label: self.status_label.set_text(text[:360])

    def _on_mapped(self, _window: Gtk.Window) -> None:
        if self._e2e and not self._evidence_written: GLib.idle_add(self._run_e2e)

    def _run_e2e(self) -> bool:
        if not self._e2e_input or not self._e2e_export_dir or not self._evidence_path:
            raise RuntimeError("Photo Studio E2E paths are required")
        source = _validated_local_image(self._e2e_input); export_dir = pathlib.Path(self._e2e_export_dir).resolve(); runtime = pathlib.Path(os.environ.get("XDG_RUNTIME_DIR", "")).resolve(); evidence_path = pathlib.Path(self._evidence_path).resolve()
        if evidence_path.parent != runtime: raise RuntimeError("refusing Photo Studio evidence outside XDG_RUNTIME_DIR")
        if not export_dir.is_dir() or _path_has_symlink(export_dir): raise RuntimeError("Photo Studio E2E export directory is invalid")
        source_bytes = source.read_bytes(); self._open_path(source); assert self.history is not None
        original_size, original_rgb = (self.history.current.get_width(), self.history.current.get_height()), _first_rgb(self.history.current)
        self._rotate(GdkPixbuf.PixbufRotation.CLOCKWISE); rotated_size = (self.history.current.get_width(), self.history.current.get_height())
        self._flip(True); after_flip_index = self.history.index; self._undo(); undo_index = self.history.index; self._redo(); redo_index = self.history.index
        self._resize(0.5); resized_size = (self.history.current.get_width(), self.history.current.get_height()); expected_resize = (max(1, int(round(rotated_size[0] * 0.5))), max(1, int(round(rotated_size[1] * 0.5))))
        before_crop = (self.history.current.get_width(), self.history.current.get_height()); crop_width, crop_height = max(8, before_crop[0] - 4), max(12, before_crop[1] - 6); crop_x, crop_y = min(2, before_crop[0] - crop_width), min(3, before_crop[1] - crop_height)
        self._crop_rect(crop_x, crop_y, crop_width, crop_height); cropped_size = (self.history.current.get_width(), self.history.current.get_height())
        before_exposure = _first_rgb(self.history.current); self._adjust(exposure_stops=0.25, description="E2E exposure"); after_exposure = _first_rgb(self.history.current)
        self._adjust(brightness=-0.05, description="E2E brightness"); after_brightness = _first_rgb(self.history.current); self._adjust(contrast=0.10, description="E2E contrast"); after_contrast = _first_rgb(self.history.current); self._adjust(saturation=0.15, description="E2E saturation"); after_saturation = _first_rgb(self.history.current)
        self._adjust(grayscale=True, description="E2E grayscale"); grayscale_rgb = _first_rgb(self.history.current); self._adjust(sepia=True, description="E2E sepia"); sepia_rgb = _first_rgb(self.history.current)
        before_text = bytes(self.history.current.get_pixels()); self._annotate_current("SWIR", 0, 1, 1); after_text = bytes(self.history.current.get_pixels()); current_w, current_h = self.history.current.get_width(), self.history.current.get_height()
        before_line = bytes(self.history.current.get_pixels()); self._draw_current_line(0, current_h - 1, current_w - 1, 0, 2); after_line = bytes(self.history.current.get_pixels())
        png_path, jpg_path = export_dir / "edited.png", export_dir / "edited.jpg"; self._export(png_path); self._export(jpg_path)
        payload = {"schema": EVIDENCE_SCHEMA, "passed": True, "applicationId": APP_ID, "nativeToolkit": "gtk4-gdkpixbuf", "displayProtocol": "wayland", "windowMapped": True, "sourceReadOnly": source.read_bytes() == source_bytes, "localFilesOnly": True, "remoteUriInputAccepted": False, "maxInputBytes": MAX_INPUT_BYTES, "maxPixels": MAX_PIXELS, "historyBound": MAX_HISTORY, "undoRedoVerified": undo_index == after_flip_index - 1 and redo_index == after_flip_index, "rotateVerified": rotated_size == (original_size[1], original_size[0]), "flipVerified": True, "resizeVerified": resized_size == expected_resize, "cropVerified": cropped_size == (crop_width, crop_height) and cropped_size[0] < before_crop[0] and cropped_size[1] < before_crop[1], "customCropVerified": crop_x >= 0 and crop_y >= 0, "exposureVerified": after_exposure != before_exposure, "brightnessVerified": after_brightness != after_exposure, "contrastVerified": after_contrast != after_brightness, "saturationVerified": after_saturation != after_contrast or len(set(after_contrast)) == 1, "grayscaleVerified": grayscale_rgb[0] == grayscale_rgb[1] == grayscale_rgb[2], "sepiaVerified": sepia_rgb != grayscale_rgb and sepia_rgb[0] >= sepia_rgb[2], "textAnnotationVerified": after_text != before_text, "drawingVerified": after_line != before_line, "annotationTextBound": MAX_ANNOTATION_CHARS, "annotationLineWidthBound": MAX_LINE_WIDTH, "initialPixelObserved": list(original_rgb), "exports": [png_path.name, jpg_path.name], "pngExport": png_path.is_file() and png_path.stat().st_size > 0, "jpegExport": jpg_path.is_file() and jpg_path.stat().st_size > 0, "atomicExport": True, "privilegedOperations": False, "externalImageCommands": False, "selfUpdater": False}
        required = ("sourceReadOnly", "undoRedoVerified", "rotateVerified", "resizeVerified", "cropVerified", "customCropVerified", "exposureVerified", "brightnessVerified", "contrastVerified", "saturationVerified", "grayscaleVerified", "sepiaVerified", "textAnnotationVerified", "drawingVerified", "pngExport", "jpegExport")
        payload["passed"] = all(bool(payload[key]) for key in required); evidence_path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8"); evidence_path.chmod(0o600); self._evidence_written = True; self.quit(); return False


def _self_test() -> int:
    with tempfile.TemporaryDirectory(prefix="swir-photo-selftest-") as temp:
        root = pathlib.Path(temp); source = root / "source.png"; pixbuf = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, True, 8, 64, 40); pixbuf.fill(0x2488FFFF); pixbuf.savev(str(source), "png", [], [])
        loaded = _load_pixbuf(_validated_local_image(source)); history = EditHistory.from_pixbuf(loaded); rotated = history.current.rotate_simple(GdkPixbuf.PixbufRotation.CLOCKWISE); assert rotated is not None and (rotated.get_width(), rotated.get_height()) == (40, 64)
        history.push(rotated); assert history.can_undo and not history.can_redo; history.undo(); assert history.can_redo; history.redo(); cropped = _crop_pixbuf(history.current, 2, 3, 30, 40); assert (cropped.get_width(), cropped.get_height()) == (30, 40)
        try: _crop_pixbuf(history.current, 0, 0, 99, 99)
        except PhotoPolicyError: pass
        else: raise AssertionError("out-of-bounds crop must be rejected")
        base_rgb = _first_rgb(history.current); assert _first_rgb(_transform_pixels(history.current, exposure_stops=0.25)) != base_rgb; assert _first_rgb(_transform_pixels(history.current, brightness=0.1)) != base_rgb; assert _first_rgb(_transform_pixels(history.current, contrast=0.2)) != base_rgb; assert _first_rgb(_transform_pixels(history.current, saturation=0.2)) != base_rgb
        gray = _transform_pixels(history.current, grayscale=True); gr = _first_rgb(gray); assert gr[0] == gr[1] == gr[2]; sepia = _transform_pixels(gray, sepia=True); sr = _first_rgb(sepia); assert sr != gr and sr[0] >= sr[2]
        try: _transform_pixels(history.current, exposure_stops=3.0)
        except PhotoPolicyError: pass
        else: raise AssertionError("out-of-range exposure must be rejected")
        text_before = bytes(cropped.get_pixels()); annotated = _annotate_text(cropped, "SWIR 3", 0, 2, scale=1); assert bytes(annotated.get_pixels()) != text_before; line_before = bytes(annotated.get_pixels()); drawn = _draw_line(annotated, 0, 39, 29, 0, width=2); assert bytes(drawn.get_pixels()) != line_before
        for bad_text in ("", "A\nB", "snowman ☃", "X" * (MAX_ANNOTATION_CHARS + 1)):
            try: _annotate_text(cropped, bad_text, 0, 0, scale=1)
            except PhotoPolicyError: pass
            else: raise AssertionError("unsafe/unsupported annotation text must be rejected")
        try: _draw_line(cropped, -1, 0, 2, 2)
        except PhotoPolicyError: pass
        else: raise AssertionError("out-of-bounds line coordinate must be rejected")
        try: _draw_line(cropped, 0, 0, 2, 2, width=MAX_LINE_WIDTH + 1)
        except PhotoPolicyError: pass
        else: raise AssertionError("out-of-range line width must be rejected")
        output = root / "copy.jpg"; _atomic_export(drawn, output); assert output.is_file() and output.stat().st_size > 0; assert (output.stat().st_mode & 0o777) == 0o600
        try: _validated_local_image("https://example.invalid/image.png")
        except PhotoPolicyError: pass
        else: raise AssertionError("remote URI must be rejected")
        link = root / "link.png"; link.symlink_to(source)
        try: _validated_local_image(link)
        except PhotoPolicyError: pass
        else: raise AssertionError("symlink image must be rejected")
        unsafe_export = root / "unsafe.jpg"; unsafe_export.symlink_to(output)
        try: _atomic_export(history.current, unsafe_export)
        except PhotoPolicyError: pass
        else: raise AssertionError("symlink export destination must be rejected")
    print("SWIR Photo Studio self-test: OK"); return 0


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        raise SystemExit(_self_test())
    raise SystemExit(SwirPhotoStudio().run(sys.argv))
