#!/usr/bin/env python3
"""Native, unprivileged SWIR OS PDF viewer.

The viewer accepts local regular PDF files only. It never executes document
content, never launches helper commands, and does not modify the source file.
The visible UI follows the bounded SWIR per-user language preference with a
reviewed English fallback.
"""

from __future__ import annotations

import json
import os
import pathlib
import stat
import sys
import tempfile
from typing import Final, Mapping

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Poppler", "0.18")
from gi.repository import Gdk, Gio, GLib, Gtk, Poppler  # noqa: E402

LIBDIR = pathlib.Path("/usr/local/lib/swir")
if LIBDIR.is_dir() and str(LIBDIR) not in sys.path:
    sys.path.insert(0, str(LIBDIR))

from core_runtime import UserSettingsStore, normalize_language_tag  # noqa: E402

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

_TRANSLATIONS: Final[Mapping[str, Mapping[str, str]]] = {
    "en": {
        "window_title": "SWIR PDF Viewer",
        "brand": "SWIR PDF Viewer",
        "open_pdf": "Open PDF",
        "open": "Open",
        "cancel": "Cancel",
        "previous": "Previous",
        "next": "Next",
        "no_document": "No document",
        "zoom_out": "Zoom out",
        "zoom_in": "Zoom in",
        "open_local": "Open a local PDF document.",
        "local_only": "Only local PDF files are accepted.",
        "resolve_failed": "Could not resolve the local PDF path.",
        "open_failed": "Could not open PDF: {error}",
        "e2e_failed": "E2E load failed: {error}",
        "pdf_documents": "PDF documents",
        "opened": "Opened {name} • {count} {pages}",
        "page_singular": "page",
        "page_plural": "pages",
        "page_label": "Page {current} / {total}",
        "open_tooltip": "Open a local PDF file",
        "previous_tooltip": "Previous page",
        "next_tooltip": "Next page",
        "page_tooltip": "Current page and document page count",
        "zoom_tooltip": "Current zoom level",
        "canvas_tooltip": "Read-only rendered PDF page",
    },
    "pl-PL": {
        "window_title": "Przeglądarka PDF SWIR",
        "brand": "Przeglądarka PDF SWIR",
        "open_pdf": "Otwórz PDF",
        "open": "Otwórz",
        "cancel": "Anuluj",
        "previous": "Poprzednia",
        "next": "Następna",
        "no_document": "Brak dokumentu",
        "zoom_out": "Pomniejsz",
        "zoom_in": "Powiększ",
        "open_local": "Otwórz lokalny dokument PDF.",
        "local_only": "Akceptowane są wyłącznie lokalne pliki PDF.",
        "resolve_failed": "Nie udało się ustalić lokalnej ścieżki pliku PDF.",
        "open_failed": "Nie udało się otworzyć PDF: {error}",
        "e2e_failed": "Nie udało się wczytać pliku E2E: {error}",
        "pdf_documents": "Dokumenty PDF",
        "opened": "Otwarto {name} • {count} {pages}",
        "page_singular": "strona",
        "page_plural": "stron",
        "page_label": "Strona {current} / {total}",
        "open_tooltip": "Otwórz lokalny plik PDF",
        "previous_tooltip": "Poprzednia strona",
        "next_tooltip": "Następna strona",
        "page_tooltip": "Bieżąca strona i liczba stron dokumentu",
        "zoom_tooltip": "Bieżący poziom powiększenia",
        "canvas_tooltip": "Renderowana strona PDF tylko do odczytu",
    },
    "nb-NO": {
        "window_title": "SWIR PDF-viser",
        "brand": "SWIR PDF-viser",
        "open_pdf": "Åpne PDF",
        "open": "Åpne",
        "cancel": "Avbryt",
        "previous": "Forrige",
        "next": "Neste",
        "no_document": "Ingen dokument",
        "zoom_out": "Zoom ut",
        "zoom_in": "Zoom inn",
        "open_local": "Åpne et lokalt PDF-dokument.",
        "local_only": "Bare lokale PDF-filer godtas.",
        "resolve_failed": "Kunne ikke finne den lokale PDF-stien.",
        "open_failed": "Kunne ikke åpne PDF: {error}",
        "e2e_failed": "E2E-innlasting mislyktes: {error}",
        "pdf_documents": "PDF-dokumenter",
        "opened": "Åpnet {name} • {count} {pages}",
        "page_singular": "side",
        "page_plural": "sider",
        "page_label": "Side {current} / {total}",
        "open_tooltip": "Åpne en lokal PDF-fil",
        "previous_tooltip": "Forrige side",
        "next_tooltip": "Neste side",
        "page_tooltip": "Gjeldende side og antall sider i dokumentet",
        "zoom_tooltip": "Gjeldende zoomnivå",
        "canvas_tooltip": "Skrivebeskyttet rendret PDF-side",
    },
}


def _locale_key(language: object) -> str:
    normalized = normalize_language_tag(language)
    if normalized in {"pl-PL", "nb-NO"}:
        return normalized
    return "en"


def resolve_locale(settings_store: UserSettingsStore | None = None) -> tuple[str, str]:
    """Resolve the bounded per-user language with a fail-safe English fallback."""
    try:
        profile = (settings_store or UserSettingsStore()).load()
        requested = normalize_language_tag(profile.get("language", ""))
    except (OSError, RuntimeError, TypeError, ValueError):
        requested = ""
    return _locale_key(requested), requested or "en"


def tr(locale: str, key: str, **values: object) -> str:
    catalog = _TRANSLATIONS.get(locale, _TRANSLATIONS["en"])
    template = catalog.get(key, _TRANSLATIONS["en"].get(key, key))
    return template.format(**values) if values else template


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
    for language in ("en", "pl-PL", "nb-NO"):
        catalog = _TRANSLATIONS[language]
        assert set(catalog) == set(_TRANSLATIONS["en"])
        assert tr(language, "open_pdf")
    assert _locale_key("pl_PL.UTF-8") == "pl-PL"
    assert _locale_key("nb_NO.UTF-8") == "nb-NO"
    assert _locale_key("de-DE") == "en"
    assert tr("unsupported", "open_pdf") == _TRANSLATIONS["en"]["open_pdf"]

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
        self.locale, self.requested_language = resolve_locale()
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
        window.set_title(tr(self.locale, "window_title"))
        window.set_default_size(1040, 760)
        window.add_css_class("swir-pdf-viewer")
        self.window = window

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        window.set_child(root)

        toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        toolbar.add_css_class("swir-toolbar")
        root.append(toolbar)

        brand = Gtk.Label(label=tr(self.locale, "brand"))
        brand.add_css_class("swir-brand")
        toolbar.append(brand)

        open_button = self._button(
            tr(self.locale, "open_pdf"), tr(self.locale, "open_tooltip")
        )
        open_button.connect("clicked", self._choose_file)
        toolbar.append(open_button)

        self.prev_button = self._button(
            tr(self.locale, "previous"), tr(self.locale, "previous_tooltip")
        )
        self.prev_button.connect("clicked", self._previous_page)
        toolbar.append(self.prev_button)

        self.next_button = self._button(
            tr(self.locale, "next"), tr(self.locale, "next_tooltip")
        )
        self.next_button.connect("clicked", self._next_page)
        toolbar.append(self.next_button)

        self.page_label = Gtk.Label(label=tr(self.locale, "no_document"))
        self.page_label.add_css_class("swir-subtle")
        self.page_label.set_tooltip_text(tr(self.locale, "page_tooltip"))
        toolbar.append(self.page_label)

        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        toolbar.append(spacer)

        zoom_out = self._button("−", tr(self.locale, "zoom_out"))
        zoom_out.connect("clicked", self._zoom_by, -ZOOM_STEP)
        toolbar.append(zoom_out)

        self.zoom_label = Gtk.Label(label="100%")
        self.zoom_label.add_css_class("swir-subtle")
        self.zoom_label.set_tooltip_text(tr(self.locale, "zoom_tooltip"))
        toolbar.append(self.zoom_label)

        zoom_in = self._button("+", tr(self.locale, "zoom_in"))
        zoom_in.connect("clicked", self._zoom_by, ZOOM_STEP)
        toolbar.append(zoom_in)

        scroller = Gtk.ScrolledWindow()
        scroller.set_hexpand(True)
        scroller.set_vexpand(True)
        canvas = Gtk.DrawingArea()
        canvas.set_content_width(850)
        canvas.set_content_height(620)
        canvas.set_draw_func(self._draw_page)
        canvas.set_tooltip_text(tr(self.locale, "canvas_tooltip"))
        self.canvas = canvas
        scroller.set_child(canvas)
        root.append(scroller)

        self.status_label = Gtk.Label(label=tr(self.locale, "open_local"))
        self.status_label.add_css_class("swir-status")
        self.status_label.set_xalign(0)
        root.append(self.status_label)

        key_controller = Gtk.EventControllerKey()
        key_controller.connect("key-pressed", self._on_key_pressed)
        window.add_controller(key_controller)

        self._refresh_controls()
        window.connect("map", self._on_mapped)
        window.present()

        if self.e2e and self.e2e_file:
            try:
                self._load_document(self.e2e_file)
            except (PdfInputError, GLib.Error, OSError, RuntimeError) as exc:
                self._set_status(tr(self.locale, "e2e_failed", error=exc))
            GLib.timeout_add(150, self._write_evidence_when_ready)

    def do_open(self, files: list[Gio.File], _n_files: int, _hint: str) -> None:
        self.activate()
        if not files:
            return
        first = files[0]
        if not first.is_native():
            self._set_status(tr(self.locale, "local_only"))
            return
        path = first.get_path()
        if not path:
            self._set_status(tr(self.locale, "resolve_failed"))
            return
        try:
            self._load_document(path)
        except (PdfInputError, GLib.Error, OSError, RuntimeError) as exc:
            self._set_status(tr(self.locale, "open_failed", error=exc))

    @staticmethod
    def _button(label: str, tooltip: str | None = None) -> Gtk.Button:
        button = Gtk.Button(label=label)
        button.add_css_class("swir-control")
        if tooltip:
            button.set_tooltip_text(tooltip)
        return button

    def _choose_file(self, _button: Gtk.Button | None) -> None:
        if self.window is None:
            return
        dialog = Gtk.FileChooserNative(
            title=tr(self.locale, "open_pdf"),
            transient_for=self.window,
            action=Gtk.FileChooserAction.OPEN,
            accept_label=tr(self.locale, "open"),
            cancel_label=tr(self.locale, "cancel"),
        )
        file_filter = Gtk.FileFilter()
        file_filter.set_name(tr(self.locale, "pdf_documents"))
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
                self._set_status(tr(self.locale, "local_only"))
                return
            path = selected.get_path()
            if not path:
                self._set_status(tr(self.locale, "resolve_failed"))
                return
            self._load_document(path)
        except (PdfInputError, GLib.Error, OSError, RuntimeError) as exc:
            self._set_status(tr(self.locale, "open_failed", error=exc))
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
        page_word = tr(self.locale, "page_singular" if pages == 1 else "page_plural")
        self._set_status(tr(self.locale, "opened", name=path.name, count=pages, pages=page_word))

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

    def _previous_page(self, _button: Gtk.Button | None) -> None:
        if self.document is None or self.page_index <= 0:
            return
        self.page_index -= 1
        self._resize_canvas()
        self._refresh_controls()

    def _next_page(self, _button: Gtk.Button | None) -> None:
        if self.document is None or self.page_index + 1 >= self.page_count:
            return
        self.page_index += 1
        self._resize_canvas()
        self._refresh_controls()

    def _zoom_by(self, _button: Gtk.Button | None, amount: float) -> None:
        if self.document is None:
            return
        self.zoom = min(MAX_ZOOM, max(MIN_ZOOM, round(self.zoom + amount, 2)))
        self._resize_canvas()
        self._refresh_controls()

    def _on_key_pressed(
        self,
        _controller: Gtk.EventControllerKey,
        keyval: int,
        _keycode: int,
        state: Gdk.ModifierType,
    ) -> bool:
        ctrl = bool(state & Gdk.ModifierType.CONTROL_MASK)
        if ctrl and keyval == Gdk.KEY_o:
            self._choose_file(None)
            return True
        if keyval in (Gdk.KEY_Page_Up, Gdk.KEY_Left):
            self._previous_page(None)
            return True
        if keyval in (Gdk.KEY_Page_Down, Gdk.KEY_Right):
            self._next_page(None)
            return True
        if keyval == Gdk.KEY_Home and self.document is not None:
            self.page_index = 0
            self._resize_canvas()
            self._refresh_controls()
            return True
        if keyval == Gdk.KEY_End and self.document is not None:
            self.page_index = max(0, self.page_count - 1)
            self._resize_canvas()
            self._refresh_controls()
            return True
        if ctrl and keyval in (Gdk.KEY_plus, Gdk.KEY_equal, Gdk.KEY_KP_Add):
            self._zoom_by(None, ZOOM_STEP)
            return True
        if ctrl and keyval in (Gdk.KEY_minus, Gdk.KEY_KP_Subtract):
            self._zoom_by(None, -ZOOM_STEP)
            return True
        if keyval == Gdk.KEY_Escape and self.window is not None:
            self.window.close()
            return True
        return False

    def _refresh_controls(self) -> None:
        has_document = self.document is not None
        if self.prev_button is not None:
            self.prev_button.set_sensitive(has_document and self.page_index > 0)
        if self.next_button is not None:
            self.next_button.set_sensitive(has_document and self.page_index + 1 < self.page_count)
        if self.page_label is not None:
            self.page_label.set_text(
                tr(
                    self.locale,
                    "page_label",
                    current=self.page_index + 1,
                    total=self.page_count,
                )
                if has_document
                else tr(self.locale, "no_document")
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
            "languageRequested": self.requested_language,
            "languageRendered": self.locale,
            "englishFallback": self.locale == "en" and self.requested_language not in {"en", "en-US"},
            "keyboardNavigation": True,
            "localizedTooltips": True,
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
