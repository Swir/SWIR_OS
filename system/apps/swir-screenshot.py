#!/usr/bin/env python3
"""SWIR Screenshot Tool — unprivileged GTK4/XDG Desktop Portal client."""
from __future__ import annotations

import json
import os
import pathlib
import stat
import sys
import tempfile
import time
import urllib.parse
import uuid
from dataclasses import dataclass
from typing import Callable, Final, Mapping

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Gdk, GdkPixbuf, Gio, GLib, Gtk  # noqa: E402

LIBDIR = pathlib.Path("/usr/local/lib/swir")
if LIBDIR.is_dir() and str(LIBDIR) not in sys.path:
    sys.path.insert(0, str(LIBDIR))

from core_runtime import UserSettingsStore, normalize_language_tag  # noqa: E402

APP_ID: Final = "dev.swir.Screenshot"
EVIDENCE_SCHEMA: Final = "swir.native-screenshot-runtime-evidence/0.2"
PORTAL_BUS: Final = "org.freedesktop.portal.Desktop"
PORTAL_PATH: Final = "/org/freedesktop/portal/desktop"
PORTAL_IFACE: Final = "org.freedesktop.portal.Screenshot"
REQUEST_IFACE: Final = "org.freedesktop.portal.Request"
MAX_CAPTURE_BYTES: Final = 64 * 1024 * 1024
MAX_PIXELS: Final = 40_000_000
MAX_PATH_BYTES: Final = 4096
COPY_CHUNK: Final = 1024 * 1024

CSS = b"""
window.swir-app { background: #02050A; color: #F4FAFF; }
.swir-header { background: #07111C; border-bottom: 1px solid #0088FF; padding: 12px; }
.swir-brand { color: #62E5FF; font-size: 20px; font-weight: 800; }
.swir-muted { color: #8DA8B8; }
.swir-panel { background: #07111C; border: 1px solid rgba(98,229,255,0.25); border-radius: 14px; padding: 12px; }
.swir-primary { background: #0088FF; color: #F4FAFF; border-radius: 9px; padding: 8px 14px; font-weight: 700; }
"""

_TRANSLATIONS: Final[Mapping[str, Mapping[str, str]]] = {
    "en": {
        "window_title": "SWIR Screenshot Tool",
        "brand": "SWIR Screenshot Tool",
        "take_screenshot": "Take Screenshot",
        "ready": "Uses the desktop portal for consent and selection.",
        "waiting": "Waiting for desktop portal selection…",
        "cancelled": "Screenshot cancelled.",
        "request_failed": "Screenshot request failed.",
        "saved": "Saved {name} — {width}×{height}",
        "capture_tooltip": "Ask the desktop portal to select and capture a screenshot",
        "preview_tooltip": "Preview of the most recently saved screenshot",
    },
    "pl-PL": {
        "window_title": "Zrzut ekranu SWIR",
        "brand": "Zrzut ekranu SWIR",
        "take_screenshot": "Zrób zrzut ekranu",
        "ready": "Używa portalu pulpitu do zgody i wyboru obszaru.",
        "waiting": "Oczekiwanie na wybór w portalu pulpitu…",
        "cancelled": "Anulowano zrzut ekranu.",
        "request_failed": "Żądanie zrzutu ekranu nie powiodło się.",
        "saved": "Zapisano {name} — {width}×{height}",
        "capture_tooltip": "Poproś portal pulpitu o wybór i wykonanie zrzutu ekranu",
        "preview_tooltip": "Podgląd ostatnio zapisanego zrzutu ekranu",
    },
    "nb-NO": {
        "window_title": "SWIR-skjermbilde",
        "brand": "SWIR-skjermbilde",
        "take_screenshot": "Ta skjermbilde",
        "ready": "Bruker skrivebordsportalen for samtykke og valg.",
        "waiting": "Venter på valg i skrivebordsportalen…",
        "cancelled": "Skjermbildet ble avbrutt.",
        "request_failed": "Forespørselen om skjermbilde mislyktes.",
        "saved": "Lagret {name} — {width}×{height}",
        "capture_tooltip": "Be skrivebordsportalen velge og ta et skjermbilde",
        "preview_tooltip": "Forhåndsvisning av sist lagrede skjermbilde",
    },
}


@dataclass(frozen=True)
class ScreenshotLocale:
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


def screenshot_locale(language: object) -> ScreenshotLocale:
    requested = normalize_language_tag(language) or "en"
    catalog = requested if requested in _TRANSLATIONS else "en"
    return ScreenshotLocale(requested, catalog, _TRANSLATIONS[catalog])


class ScreenshotPolicyError(RuntimeError):
    pass


def _path_has_symlink(path: pathlib.Path, *, allow_missing_leaf: bool = False) -> bool:
    absolute = path if path.is_absolute() else pathlib.Path.cwd() / path
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


def _validated_portal_uri(raw_uri: str) -> pathlib.Path:
    if not isinstance(raw_uri, str) or len(raw_uri.encode("utf-8", errors="ignore")) > MAX_PATH_BYTES * 3:
        raise ScreenshotPolicyError("portal screenshot URI is invalid or too long")
    parsed = urllib.parse.urlsplit(raw_uri)
    if parsed.scheme != "file" or parsed.netloc not in ("", "localhost") or parsed.query or parsed.fragment:
        raise ScreenshotPolicyError("portal screenshot must be a local file URI")
    text = urllib.parse.unquote(parsed.path)
    if not text.startswith("/") or "\x00" in text:
        raise ScreenshotPolicyError("portal screenshot path is invalid")
    path = pathlib.Path(text)
    if len(os.fsencode(path)) > MAX_PATH_BYTES or _path_has_symlink(path):
        raise ScreenshotPolicyError("portal screenshot path is unsafe")
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise ScreenshotPolicyError(f"portal screenshot cannot be resolved: {exc}") from exc
    if resolved != path:
        raise ScreenshotPolicyError("portal screenshot path must be canonical")
    st = resolved.stat()
    if not stat.S_ISREG(st.st_mode) or st.st_size <= 0 or st.st_size > MAX_CAPTURE_BYTES:
        raise ScreenshotPolicyError("portal screenshot is not a bounded regular file")
    if not os.access(resolved, os.R_OK):
        raise ScreenshotPolicyError("portal screenshot is not readable")
    return resolved


def _decode_verified_image(path: pathlib.Path) -> tuple[int, int]:
    try:
        info = GdkPixbuf.Pixbuf.get_file_info(str(path))
    except GLib.Error as exc:
        raise ScreenshotPolicyError(f"portal screenshot decode failed: {exc.message}") from exc
    if not info:
        raise ScreenshotPolicyError("portal screenshot is not a supported image")
    _fmt, width, height = info
    if width <= 0 or height <= 0 or width * height > MAX_PIXELS:
        raise ScreenshotPolicyError("portal screenshot dimensions exceed the verified bound")
    return width, height


def _ensure_owner_directory(path: pathlib.Path, *, create: bool) -> pathlib.Path:
    path = path.expanduser().absolute()
    if len(os.fsencode(path)) > MAX_PATH_BYTES or _path_has_symlink(path, allow_missing_leaf=create):
        raise ScreenshotPolicyError("screenshot destination path is unsafe")
    if create:
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.is_symlink() or not path.is_dir() or path.stat().st_uid != os.getuid():
        raise ScreenshotPolicyError("screenshot destination is not a user-owned real directory")
    if not os.access(path, os.W_OK | os.X_OK):
        raise ScreenshotPolicyError("screenshot destination is not writable")
    try:
        path.chmod(0o700)
    except OSError:
        pass
    return path


def _default_output_directory() -> pathlib.Path:
    override = os.environ.get("SWIR_SCREENSHOT_E2E_OUTPUT_DIR", "")
    if override and os.environ.get("SWIR_APP_E2E") == "1":
        candidate = pathlib.Path(override)
        if not candidate.is_absolute():
            raise ScreenshotPolicyError("E2E output override must be absolute")
        return _ensure_owner_directory(candidate, create=True)
    pictures = GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_PICTURES)
    root = pathlib.Path(pictures) if pictures else pathlib.Path.home() / "Pictures"
    if root.exists() and (root.is_symlink() or root.stat().st_uid != os.getuid()):
        raise ScreenshotPolicyError("Pictures directory is unsafe")
    root.mkdir(mode=0o755, parents=True, exist_ok=True)
    return _ensure_owner_directory(root / "Screenshots", create=True)


def _unique_destination(directory: pathlib.Path) -> pathlib.Path:
    stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime())
    for suffix in range(1000):
        tail = "" if suffix == 0 else f"-{suffix}"
        candidate = directory / f"SWIR-Screenshot-{stamp}{tail}.png"
        if not candidate.exists() and not candidate.is_symlink():
            return candidate
    raise ScreenshotPolicyError("could not allocate a unique screenshot name")


def _atomic_copy_capture(source: pathlib.Path, directory: pathlib.Path) -> pathlib.Path:
    source = _validated_portal_uri(source.as_uri())
    _decode_verified_image(source)
    directory = _ensure_owner_directory(directory, create=True)
    destination = _unique_destination(directory)
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    source_fd = os.open(source, flags)
    tmp_fd, tmp_name = tempfile.mkstemp(prefix=".swir-shot-", suffix=".png", dir=directory)
    tmp = pathlib.Path(tmp_name)
    total = 0
    try:
        source_stat = os.fstat(source_fd)
        if not stat.S_ISREG(source_stat.st_mode) or not 0 < source_stat.st_size <= MAX_CAPTURE_BYTES:
            raise ScreenshotPolicyError("portal screenshot changed before copy")
        with os.fdopen(source_fd, "rb", closefd=True) as src, os.fdopen(tmp_fd, "wb", closefd=True) as dst:
            source_fd = -1
            tmp_fd = -1
            while True:
                chunk = src.read(COPY_CHUNK)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_CAPTURE_BYTES:
                    raise ScreenshotPolicyError("portal screenshot exceeded copy bound")
                dst.write(chunk)
            dst.flush()
            os.fsync(dst.fileno())
        if total != source_stat.st_size:
            raise ScreenshotPolicyError("portal screenshot changed during copy")
        os.chmod(tmp, 0o600)
        _decode_verified_image(tmp)
        os.replace(tmp, destination)
        os.chmod(destination, 0o600)
        return destination
    finally:
        if source_fd >= 0:
            os.close(source_fd)
        if tmp_fd >= 0:
            os.close(tmp_fd)
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass


class PortalScreenshotClient:
    def __init__(self) -> None:
        self.connection = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        self.proxy = Gio.DBusProxy.new_sync(self.connection, Gio.DBusProxyFlags.DO_NOT_LOAD_PROPERTIES, None, PORTAL_BUS, PORTAL_PATH, PORTAL_IFACE, None)
        self.subscription_id = 0
        self.expected_handle = ""
        self.pending: dict[str, tuple[int, dict[str, object]]] = {}
        self.callback: Callable[[int, dict[str, object]], None] | None = None

    def request(self, callback: Callable[[int, dict[str, object]], None]) -> None:
        if self.callback is not None:
            raise ScreenshotPolicyError("a screenshot request is already active")
        self.callback = callback
        self.subscription_id = self.connection.signal_subscribe(PORTAL_BUS, REQUEST_IFACE, "Response", None, None, Gio.DBusSignalFlags.NONE, self._on_response)
        options = {"handle_token": GLib.Variant("s", "swir" + uuid.uuid4().hex[:20]), "interactive": GLib.Variant("b", True)}
        self.proxy.call("Screenshot", GLib.Variant("(sa{sv})", ("", options)), Gio.DBusCallFlags.NONE, -1, None, self._on_requested)

    def _on_requested(self, proxy: Gio.DBusProxy, result: Gio.AsyncResult) -> None:
        try:
            handle = str(proxy.call_finish(result).unpack()[0])
            if not handle.startswith("/org/freedesktop/portal/desktop/request/"):
                raise ScreenshotPolicyError("portal returned an unexpected request handle")
            self.expected_handle = handle
            pending = self.pending.pop(handle, None)
            if pending is not None:
                self._complete(*pending)
        except (GLib.Error, ScreenshotPolicyError) as exc:
            self._complete(2, {"error": f"portal screenshot request failed: {exc}"})

    def _on_response(self, _connection, _sender, object_path, _interface, _signal, parameters) -> None:
        response, results = parameters.unpack()
        payload = dict(results)
        if self.expected_handle and object_path == self.expected_handle:
            self._complete(int(response), payload)
        else:
            self.pending[str(object_path)] = (int(response), payload)

    def _complete(self, response: int, results: dict[str, object]) -> None:
        callback = self.callback
        if self.subscription_id:
            self.connection.signal_unsubscribe(self.subscription_id)
        self.subscription_id = 0
        self.expected_handle = ""
        self.pending.clear()
        self.callback = None
        if callback is not None:
            callback(response, results)


class SwirScreenshot(Gtk.Application):
    def __init__(self) -> None:
        super().__init__(application_id=APP_ID)
        self.window: Gtk.ApplicationWindow | None = None
        self.picture: Gtk.Picture | None = None
        self.status: Gtk.Label | None = None
        self.capture_button: Gtk.Button | None = None
        self.portal: PortalScreenshotClient | None = None
        self.settings_store = UserSettingsStore()
        self.locale = self._load_locale()
        self._e2e = os.environ.get("SWIR_APP_E2E") == "1"
        self._evidence_path = os.environ.get("SWIR_APP_EVIDENCE_PATH", "")
        self._mapped = False

    def _load_locale(self) -> ScreenshotLocale:
        try:
            language = self.settings_store.load().get("language", "en")
        except (OSError, RuntimeError, UnicodeError, ValueError):
            language = "en"
        return screenshot_locale(language)

    def _t(self, key: str, **values: object) -> str:
        return self.locale.text(key, **values)

    def do_startup(self) -> None:
        Gtk.Application.do_startup(self)
        provider = Gtk.CssProvider()
        provider.load_from_data(CSS)
        display = Gdk.Display.get_default()
        if display is None:
            raise RuntimeError("SWIR Screenshot Tool requires an active graphical display")
        Gtk.StyleContext.add_provider_for_display(display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    def do_activate(self) -> None:
        if self.window is None:
            self._build_ui()
        assert self.window is not None
        self.window.present()
        if self._e2e:
            GLib.timeout_add(250, self._start_e2e_capture)

    def _build_ui(self) -> None:
        window = Gtk.ApplicationWindow(application=self)
        window.set_title(self._t("window_title"))
        window.set_default_size(780, 560)
        window.add_css_class("swir-app")
        direction = Gtk.TextDirection.RTL if self.locale.text_direction == "rtl" else Gtk.TextDirection.LTR
        window.set_direction(direction)
        window.connect("map", lambda *_: setattr(self, "_mapped", True))
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        header.add_css_class("swir-header")
        brand = Gtk.Label(label=self._t("brand"), xalign=0)
        brand.add_css_class("swir-brand")
        header.append(brand)
        outer.append(header)
        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        body.set_margin_top(18); body.set_margin_bottom(18); body.set_margin_start(18); body.set_margin_end(18)
        body.add_css_class("swir-panel")
        capture = Gtk.Button(label=self._t("take_screenshot"))
        capture.add_css_class("swir-primary")
        capture.set_focusable(True)
        capture.set_tooltip_text(self._t("capture_tooltip"))
        capture.connect("clicked", lambda *_: self._capture())
        body.append(capture)
        status_label = Gtk.Label(label=self._t("ready"), xalign=0)
        status_label.set_wrap(True); status_label.set_selectable(True); status_label.add_css_class("swir-muted")
        body.append(status_label)
        picture = Gtk.Picture(); picture.set_can_shrink(True); picture.set_content_fit(Gtk.ContentFit.CONTAIN); picture.set_vexpand(True)
        picture.set_tooltip_text(self._t("preview_tooltip"))
        body.append(picture)
        outer.append(body)
        window.set_child(outer)
        self.window, self.picture, self.status, self.capture_button = window, picture, status_label, capture

    def _set_status(self, text: str) -> None:
        if self.status is not None:
            self.status.set_text(text)

    def _capture(self) -> None:
        if self.capture_button is not None:
            self.capture_button.set_sensitive(False)
        self._set_status(self._t("waiting"))
        try:
            self.portal = PortalScreenshotClient()
            self.portal.request(self._portal_response)
        except (GLib.Error, ScreenshotPolicyError) as exc:
            self._capture_failed(str(exc))

    def _portal_response(self, response: int, results: dict[str, object]) -> None:
        if response != 0:
            default = self._t("cancelled") if response == 1 else self._t("request_failed")
            self._capture_failed(str(results.get("error", default)))
            return
        try:
            uri = results.get("uri")
            if not isinstance(uri, str):
                raise ScreenshotPolicyError("portal response did not contain a screenshot URI")
            source = _validated_portal_uri(uri)
            width, height = _decode_verified_image(source)
            destination = _atomic_copy_capture(source, _default_output_directory())
            if self.picture is not None:
                self.picture.set_filename(str(destination))
            self._set_status(self._t("saved", name=destination.name, width=width, height=height))
            if self.capture_button is not None:
                self.capture_button.set_sensitive(True)
            if self._e2e:
                self._write_evidence(destination, width, height)
                GLib.idle_add(self.quit)
        except (OSError, GLib.Error, ScreenshotPolicyError) as exc:
            self._capture_failed(str(exc))

    def _capture_failed(self, message: str) -> None:
        self._set_status(message)
        if self.capture_button is not None:
            self.capture_button.set_sensitive(True)
        if self._e2e:
            print(f"SWIR Screenshot E2E failed: {message}", file=sys.stderr)
            GLib.idle_add(self.quit)

    def _start_e2e_capture(self) -> bool:
        self._capture()
        return False

    def _write_evidence(self, destination: pathlib.Path, width: int, height: int) -> None:
        if not self._evidence_path:
            return
        path = pathlib.Path(self._evidence_path)
        runtime_text = os.environ.get("XDG_RUNTIME_DIR", "")
        if not runtime_text or path.parent.resolve() != pathlib.Path(runtime_text).resolve():
            raise ScreenshotPolicyError("refusing SWIR Screenshot evidence path outside XDG_RUNTIME_DIR")
        localized_surface_verified = bool(
            self.window
            and self.window.get_title() == self._t("window_title")
            and self.capture_button
            and self.capture_button.get_label() == self._t("take_screenshot")
        )
        localized_tooltips = bool(
            self.capture_button
            and self.capture_button.get_tooltip_text() == self._t("capture_tooltip")
            and self.picture
            and self.picture.get_tooltip_text() == self._t("preview_tooltip")
        )
        payload = {
            "schema": EVIDENCE_SCHEMA, "passed": self._mapped and localized_surface_verified and localized_tooltips,
            "applicationId": APP_ID,
            "nativeToolkit": "gtk4-gdkpixbuf", "displayProtocol": "wayland" if os.environ.get("WAYLAND_DISPLAY") else "unknown",
            "windowMapped": self._mapped, "portalBus": PORTAL_BUS, "portalInterface": PORTAL_IFACE,
            "portalRequestUsed": True, "interactiveRequest": True, "sourceUriScheme": "file", "sourceValidated": True,
            "savedFile": destination.name, "savedMode": f"{stat.S_IMODE(destination.stat().st_mode):04o}", "dimensions": [width, height],
            "remoteUriAccepted": False, "shellCapture": False, "privilegedOperations": False, "selfUpdater": False,
            "requestedLanguage": self.locale.requested_language, "catalogLanguage": self.locale.catalog_language,
            "translationFallback": self.locale.fallback, "textDirection": self.locale.text_direction,
            "localizedWindowTitle": self._t("window_title"), "localizedCaptureLabel": self._t("take_screenshot"),
            "localizedSurfaceVerified": localized_surface_verified,
            "captureButtonFocusable": bool(self.capture_button and self.capture_button.get_focusable()),
            "localizedTooltips": localized_tooltips,
            "evidenceOwnerOnly": True,
        }
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        path.chmod(0o600)


def _self_test() -> int:
    with tempfile.TemporaryDirectory(prefix="swir-screenshot-selftest-") as raw:
        root = pathlib.Path(raw)
        source = root / "capture.png"
        pixbuf = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, True, 8, 32, 20)
        pixbuf.fill(0x0088FFFF); pixbuf.savev(str(source), "png", [], [])
        assert _validated_portal_uri(source.as_uri()) == source.resolve()
        assert _decode_verified_image(source) == (32, 20)
        out = root / "out"; out.mkdir(mode=0o700)
        copied = _atomic_copy_capture(source, out)
        assert copied.is_file() and stat.S_IMODE(copied.stat().st_mode) == 0o600
        assert screenshot_locale("pl-PL").text("take_screenshot") == "Zrób zrzut ekranu"
        assert screenshot_locale("nb-NO").text("take_screenshot") == "Ta skjermbilde"
        fallback = screenshot_locale("zz-ZZ")
        assert fallback.catalog_language == "en" and fallback.fallback is True
        for bad in ("https://example.invalid/a.png", "data:image/png;base64,AAAA", "file://remotehost/tmp/a.png"):
            try:
                _validated_portal_uri(bad)
            except ScreenshotPolicyError:
                pass
            else:
                raise AssertionError(f"unsafe screenshot URI accepted: {bad}")
        link = root / "link.png"; link.symlink_to(source)
        try:
            _validated_portal_uri(link.as_uri())
        except ScreenshotPolicyError:
            pass
        else:
            raise AssertionError("symlink screenshot source accepted")
    print("SWIR Screenshot Tool self-test: OK")
    return 0


def main(argv: list[str]) -> int:
    if "--self-test" in argv:
        return _self_test()
    return int(SwirScreenshot().run(argv))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))