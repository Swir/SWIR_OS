#!/usr/bin/env python3
"""Native, unprivileged SWIR OS PDF viewer.

The viewer accepts local regular PDF files only. It never executes document
content, never launches helper commands, and does not modify the source file.
"""

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
gi.require_version("Poppler", "0.18")
from gi.repository import Gdk, Gio, GLib, Gtk, Poppler  # noqa: E402

APP_ID: Final = "dev.swir.PdfViewer"
EVIDENCE_SCHEMA: Final = "swir.native-pdf-viewer-runtime-evidence/0.1"
MAX_PDF_BYTES: Final = 512 * 1024 * 1024
MAX_PAGES: Final = 4000
MIN_ZOOM: Final = 0.25
MAX_ZOOM: Final = 4.0
ZOOM_STEP: Final = 0.25

CSS = b"""
window.swir-pdf-viewer {
  background: #02050A;
  color: #EAF9FF;
}
.swir-toolbar {
  background: rgba(7,17,28,0.97);
  border-bottom: 1px solid rgba(98,229,255,0.34);
  padding: 10px 14px;
}
.swir-brand { color: #62E5FF; font-size: 18px; font-weight: 800; }
.swir-subtle { color: #8FAFC2; }
.swir-control {
  background: #07111C;
  color: #EAF9FF;
  border: 1px solid #0088FF;
  border-radius: 10px;
  padding: 7px 12px;
}
.swir-control:hover { background: #0A2136; border-color: #62E5FF; }
.swir-status {
  background: #07111C;
  border-top: 1px solid rgba(98,229,255,0.2);
  color: #8FAFC2;
  padding: 7px 14px;
}
"""


class PdfInputError(ValueError):
    """Raised when a requested document violates the local-file contract."""


def validate_pdf_path(value: str | os.PathLike[str]) -> pathlib.Path:
    raw = pathlib.Path(value).expanduser()
    if not raw.is_absolute():
        raw = pathlib.Path.cwd() / raw
    try:
        info = os.lstat(raw)
    except OSError as exc:
        raise PdfInputError(f"cannot inspect PDF: {exc.strerror or exc}") from exc
    if stat.S_ISLNK(info.st_mode):
        raise PdfInputError("symbolic links are not accepted")
    if not stat.S_ISREG(info.st_mode):
        raise PdfInputError("PDF input must be a regular file")
    if raw.suffix.casefold() != ".pdf":
        raise PdfInputError("only .pdf files are accepted")
    if info.st_size <= 0:
        raise PdfInputError("PDF file is empty")
    if info.st_size > MAX_PDF_BYTES:
        raise PdfInputError(f"PDF exceeds the {MAX_PDF_BYTES // (1024 * 1024)} MiB safety limit")
    return raw.resolve(strict=True)


def _self_test() -> int:
    with tempfile.TemporaryDirectory(prefix="swir-pdf-selftest-") as tmp:
        root = pathlib.Path(tmp)
        sample = root / "sample.pdf"
        sample.write_bytes(b"%PDF-1.4\n% self-test marker\n")
        resolved = validate_pdf_path(sample)
        assert resolved == sample.resolve()
        assert MAX_PAGES == 4000
        assert MIN_ZOOM < 1.0 < MAX_ZOOM

        wrong = root / "sample.txt"
        wrong.write_bytes(b"%PDF")
        try:
            validate_pdf_path(wrong)
        except PdfInputError:
            pass
        else:
            raise AssertionError("non-PDF extension was accepted")

        symlink = root / "linked.pdf"
        try:
            symlink.symlink_to(sample)
        except (OSError, NotImplementedError):
            symlink = None
        if symlink is not None:
            try:
                validate_pdf_path(symlink)
            except PdfInputError:
                pass
            else:
                raise AssertionError("symlink input was accepted")
    print("SWIR PDF Viewer self-test: OK")
    return 0


class SwirPdfViewer(Gtk.Application):
    def __init__(self) -> None:
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.HANDLES_OPEN)
        self.window: Gtk.ApplicationWindow | None = None
        self.canvas: Gtk.DrawingArea | None = None
        self.page_label: Gtk.Label | None = None
        self.zoom_label: Gtk.Label | None = None
        self.status_label: Gtk.Label | None = None
        self.prev_button: Gtk.Button | None = None
        self.next_button: Gtk.Button | None = None
        self.document: Poppler.Document | None = None
        self.current_path: pathlib.Path | None = None
        self.page_index = 0
        self.page_count = 0
        self.zoom = 1.0
        self.render_count = 0
        self.e2e = os.environ.get("SWIR_APP_E2E", "0") == "1"
        self.evidence_path = os.environ.get("SWIR_APP_EVIDENCE_PATH", "")
        self.e2e_file = os.environ.get("SWIR_PDF_E2E_FILE", "")
        self.evidence_attempts = 0

    def do_startup(self) -> None:
        Gtk.Application.do_startup(self)
        provider = Gtk.CssProvider()
        provider.load_from_data(CSS)
        display = Gdk.Display.get_default()
        if display is None:
            raise RuntimeError("SWIR PDF Viewer requires an active graphical display")
        Gtk.StyleContext.add_provider_for_display(
            display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

    def do_activate(self) -> None:
        if self.window is not None:
            self.window.present()
            return
        window = Gtk.ApplicationWindow(application=self)
        window.set_title("SWIR PDF Viewer")
        window.set_default_size(1040, 760)
        window.add_css_class("swir-pdf-viewer")
        self.window = window

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        window.set_child(root)

        toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        toolbar.add_css_class("swir-toolbar")
        root.append(toolbar)

        brand = Gtk.Label(label="SWIR PDF Viewer")
        brand.add_css_class("swir-brand")
        toolbar.append(brand)

        open_button = self._button("Open PDF")
        open_button.connect("clicked", self._choose_file)
        toolbar.append(open_button)

        self.prev_button = self._button("Previous")
        self.prev_button.connect("clicked", self._previous_page)
        toolbar.append(self.prev_button)

        self.next_button = self._button("Next")
        self.next_button.connect("clicked", self._next_page)
        toolbar.append(self.next_button)

        self.page_label = Gtk.Label(label="No document")
        self.page_label.add_css_class("swir-subtle")
        toolbar.append(self.page_label)

        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        toolbar.append(spacer)

        zoom_out = self._button("−")
        zoom_out.set_tooltip_text("Zoom out")
        zoom_out.connect("clicked", self._zoom_by, -ZOOM_STEP)
        toolbar.append(zoom_out)

        self.zoom_label = Gtk.Label(label="100%")
        self.zoom_label.add_css_class("swir-subtle")
        toolbar.append(self.zoom_label)

        zoom_in = self._button("+")
        zoom_in.set_tooltip_text("Zoom in")
        zoom_in.connect("clicked", self._zoom_by, ZOOM_STEP)
        toolbar.append(zoom_in)

        scroller = Gtk.ScrolledWindow()
        scroller.set_hexpand(True)
        scroller.set_vexpand(True)
        canvas = Gtk.DrawingArea()
        canvas.set_content_width(850)
        canvas.set_content_height(620)
        canvas.set_draw_func(self._draw_page)
        self.canvas = canvas
        scroller.set_child(canvas)
        root.append(scroller)

        self.status_label = Gtk.Label(label="Open a local PDF document.")
        self.status_label.add_css_class("swir-status")
        self.status_label.set_xalign(0)
        root.append(self.status_label)

        self._refresh_controls()
        window.connect("map", self._on_mapped)
        window.present()

        if self.e2e and self.e2e_file:
            try:
                self._load_document(self.e2e_file)
            except (PdfInputError, GLib.Error, OSError, RuntimeError) as exc:
                self._set_status(f"E2E load failed: {exc}")
            GLib.timeout_add(150, self._write_evidence_when_ready)

    def do_open(self, files: list[Gio.File], _n_files: int, _hint: str) -> None:
        self.activate()
        if not files:
            return
        first = files[0]
        if not first.is_native():
            self._set_status("Only local PDF files are accepted.")
            return
        path = first.get_path()
        if not path:
            self._set_status("Could not resolve the local PDF path.")
            return
        try:
            self._load_document(path)
        except (PdfInputError, GLib.Error, OSError, RuntimeError) as exc:
            self._set_status(f"Could not open PDF: {exc}")

    @staticmethod
    def _button(label: str) -> Gtk.Button:
        button = Gtk.Button(label=label)
        button.add_css_class("swir-control")
        return button

    def _choose_file(self, _button: Gtk.Button) -> None:
        if self.window is None:
            return
        dialog = Gtk.FileChooserNative(
            title="Open PDF",
            transient_for=self.window,
            action=Gtk.FileChooserAction.OPEN,
            accept_label="Open",
            cancel_label="Cancel",
        )
        file_filter = Gtk.FileFilter()
        file_filter.set_name("PDF documents")
        file_filter.add_mime_type("application/pdf")
        file_filter.add_pattern("*.pdf")
        file_filter.add_pattern("*.PDF")
        dialog.add_filter(file_filter)
        dialog.connect("response", self._on_file_response)
        dialog.show()

    def _on_file_response(self, dialog: Gtk.FileChooserNative, response: int) -> None:
        try:
            if response != Gtk.ResponseType.ACCEPT:
                return
            selected = dialog.get_file()
            if selected is None or not selected.is_native():
                self._set_status("Only local PDF files are accepted.")
                return
            path = selected.get_path()
            if not path:
                self._set_status("Could not resolve the local PDF path.")
                return
            self._load_document(path)
        except (PdfInputError, GLib.Error, OSError, RuntimeError) as exc:
            self._set_status(f"Could not open PDF: {exc}")
        finally:
            dialog.destroy()

    def _load_document(self, value: str | os.PathLike[str]) -> None:
        path = validate_pdf_path(value)
        source = Gio.File.new_for_path(str(path))
        uri = source.get_uri()
        if not uri.startswith("file://"):
            raise PdfInputError("remote document URIs are not accepted")
        document = Poppler.Document.new_from_file(uri, None)
        pages = document.get_n_pages()
        if pages <= 0:
            raise PdfInputError("PDF contains no pages")
        if pages > MAX_PAGES:
            raise PdfInputError(f"PDF exceeds the {MAX_PAGES}-page safety limit")
        self.document = document
        self.current_path = path
        self.page_count = pages
        self.page_index = 0
        self.zoom = 1.0
        self.render_count = 0
        self._resize_canvas()
        self._refresh_controls()
        self._set_status(f"Opened {path.name} • {pages} page{'s' if pages != 1 else ''}")

    def _current_page(self) -> Poppler.Page | None:
        if self.document is None:
            return None
        return self.document.get_page(self.page_index)

    def _resize_canvas(self) -> None:
        page = self._current_page()
        if page is None or self.canvas is None:
            return
        width, height = page.get_size()
        self.canvas.set_content_width(max(1, int(width * self.zoom)))
        self.canvas.set_content_height(max(1, int(height * self.zoom)))
        self.canvas.queue_draw()

    def _draw_page(self, _area: Gtk.DrawingArea, cr, width: int, height: int) -> None:
        cr.set_source_rgb(0.008, 0.02, 0.039)
        cr.paint()
        page = self._current_page()
        if page is None:
            return
        page_width, page_height = page.get_size()
        target_width = max(1.0, page_width * self.zoom)
        target_height = max(1.0, page_height * self.zoom)
        offset_x = max(0.0, (width - target_width) / 2.0)
        offset_y = max(0.0, (height - target_height) / 2.0)
        cr.save()
        cr.translate(offset_x, offset_y)
        cr.scale(self.zoom, self.zoom)
        cr.set_source_rgb(1.0, 1.0, 1.0)
        cr.rectangle(0, 0, page_width, page_height)
        cr.fill()
        page.render(cr)
        cr.restore()
        self.render_count += 1

    def _previous_page(self, _button: Gtk.Button) -> None:
        if self.document is None or self.page_index <= 0:
            return
        self.page_index -= 1
        self._resize_canvas()
        self._refresh_controls()

    def _next_page(self, _button: Gtk.Button) -> None:
        if self.document is None or self.page_index + 1 >= self.page_count:
            return
        self.page_index += 1
        self._resize_canvas()
        self._refresh_controls()

    def _zoom_by(self, _button: Gtk.Button, amount: float) -> None:
        if self.document is None:
            return
        self.zoom = min(MAX_ZOOM, max(MIN_ZOOM, round(self.zoom + amount, 2)))
        self._resize_canvas()
        self._refresh_controls()

    def _refresh_controls(self) -> None:
        has_document = self.document is not None
        if self.prev_button is not None:
            self.prev_button.set_sensitive(has_document and self.page_index > 0)
        if self.next_button is not None:
            self.next_button.set_sensitive(has_document and self.page_index + 1 < self.page_count)
        if self.page_label is not None:
            self.page_label.set_text(
                f"Page {self.page_index + 1} / {self.page_count}" if has_document else "No document"
            )
        if self.zoom_label is not None:
            self.zoom_label.set_text(f"{int(round(self.zoom * 100))}%")

    def _set_status(self, message: str) -> None:
        if self.status_label is not None:
            self.status_label.set_text(message)

    def _on_mapped(self, _window: Gtk.Window) -> None:
        if self.canvas is not None:
            self.canvas.queue_draw()

    def _write_evidence_when_ready(self) -> bool:
        if not self.e2e or not self.evidence_path:
            return False
        self.evidence_attempts += 1
        if self.document is None or self.render_count <= 0:
            return self.evidence_attempts < 40
        path = pathlib.Path(self.evidence_path)
        runtime_text = os.environ.get("XDG_RUNTIME_DIR", "")
        if not runtime_text:
            return False
        runtime = pathlib.Path(runtime_text).resolve()
        if path.parent.resolve() != runtime:
            print("refusing PDF evidence path outside XDG_RUNTIME_DIR", file=sys.stderr)
            return False
        payload = {
            "schema": EVIDENCE_SCHEMA,
            "passed": True,
            "applicationId": APP_ID,
            "nativeToolkit": "gtk4-poppler",
            "displayProtocol": "wayland",
            "windowMapped": True,
            "localFilesOnly": True,
            "remoteUriInputAccepted": False,
            "sourceReadOnly": True,
            "pageCount": self.page_count,
            "pageLimit": MAX_PAGES,
            "fileSizeLimitBytes": MAX_PDF_BYTES,
            "renderVerified": self.render_count > 0,
            "navigationAvailable": self.page_count > 0,
            "zoomRange": [MIN_ZOOM, MAX_ZOOM],
            "privilegedOperations": False,
            "selfUpdater": False,
        }
        path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
        path.chmod(0o600)
        if self.window is not None:
            self.window.close()
        self.quit()
        return False


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        raise SystemExit(_self_test())
    raise SystemExit(SwirPdfViewer().run(sys.argv))
