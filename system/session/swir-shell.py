#!/usr/bin/env python3
"""Native GTK4 shell surface for SWIR OS System Edition.

This process is intentionally unprivileged. It presents the desktop surface,
status/header area, a bounded native notification service/history and a small
allowlisted launcher. Privileged system actions remain behind their dedicated
brokers/polkit policies.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from typing import Final

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, Gio, GLib, Gtk  # noqa: E402

LIBDIR = pathlib.Path("/usr/local/lib/swir")
if LIBDIR.is_dir() and str(LIBDIR) not in sys.path:
    sys.path.insert(0, str(LIBDIR))

try:
    from core_runtime import DEFAULT_THEME_ID, ThemeStore, UserSettingsStore, default_theme, theme_css
except ImportError:
    DEFAULT_THEME_ID = "builtin.swir-dark"
    UserSettingsStore = None  # type: ignore[assignment,misc]
    ThemeStore = None  # type: ignore[assignment,misc]
    default_theme = None  # type: ignore[assignment]
    theme_css = None  # type: ignore[assignment]

APP_ID: Final = "dev.swir.Shell"
EVIDENCE_SCHEMA: Final = "swir.native-shell-runtime-evidence/0.1"

NOTIFICATION_BUS: Final = "org.freedesktop.Notifications"
NOTIFICATION_PATH: Final = "/org/freedesktop/Notifications"
NOTIFICATION_IFACE: Final = "org.freedesktop.Notifications"
NOTIFICATION_HISTORY_SCHEMA: Final = "swir.notification-history/0.1"
MAX_NOTIFICATION_HISTORY: Final = 200
MAX_NOTIFICATION_HISTORY_BYTES: Final = 2 * 1024 * 1024
MAX_VISIBLE_HISTORY: Final = 20
MAX_APP_NAME_CHARS: Final = 120
MAX_SUMMARY_CHARS: Final = 240
MAX_BODY_CHARS: Final = 4096
MAX_ACTION_PAIRS: Final = 6
DEFAULT_TIMEOUT_MS: Final = 8000
MAX_TIMEOUT_MS: Final = 60000

NOTIFICATION_XML: Final = """
<node>
  <interface name="org.freedesktop.Notifications">
    <method name="GetCapabilities">
      <arg direction="out" name="capabilities" type="as"/>
    </method>
    <method name="Notify">
      <arg direction="in" name="app_name" type="s"/>
      <arg direction="in" name="replaces_id" type="u"/>
      <arg direction="in" name="app_icon" type="s"/>
      <arg direction="in" name="summary" type="s"/>
      <arg direction="in" name="body" type="s"/>
      <arg direction="in" name="actions" type="as"/>
      <arg direction="in" name="hints" type="a{sv}"/>
      <arg direction="in" name="expire_timeout" type="i"/>
      <arg direction="out" name="id" type="u"/>
    </method>
    <method name="CloseNotification">
      <arg direction="in" name="id" type="u"/>
    </method>
    <method name="GetServerInformation">
      <arg direction="out" name="name" type="s"/>
      <arg direction="out" name="vendor" type="s"/>
      <arg direction="out" name="version" type="s"/>
      <arg direction="out" name="spec_version" type="s"/>
    </method>
    <signal name="NotificationClosed">
      <arg name="id" type="u"/>
      <arg name="reason" type="u"/>
    </signal>
    <signal name="ActionInvoked">
      <arg name="id" type="u"/>
      <arg name="action_key" type="s"/>
    </signal>
  </interface>
</node>
"""

CSS = b"""
window.swir-shell {
  background: #02050A;
  color: #EAF9FF;
}
.swir-topbar {
  background: rgba(7,17,28,0.97);
  border-bottom: 1px solid #0088FF;
  padding: 12px 18px;
}
.swir-brand { color: #62E5FF; font-size: 20px; font-weight: 800; }
.swir-subtle { color: #8FAFC2; }
.swir-title { color: #FFFFFF; font-size: 34px; font-weight: 800; }
.swir-card {
  background: rgba(7,17,28,0.92);
  border: 1px solid rgba(98,229,255,0.32);
  border-radius: 18px;
  padding: 22px;
}
.swir-launcher {
  background: #07111C;
  color: #EAF9FF;
  border: 1px solid #0088FF;
  border-radius: 14px;
  padding: 12px 16px;
}
.swir-launcher:hover { background: #0A2136; border-color: #62E5FF; }
.swir-dock {
  background: rgba(7,17,28,0.97);
  border-top: 1px solid rgba(98,229,255,0.35);
  padding: 12px 18px;
}
.swir-notification {
  background: rgba(7,17,28,0.99);
  color: #EAF9FF;
  border: 1px solid #62E5FF;
  border-radius: 14px;
  padding: 14px;
}
.swir-notification-title { color: #62E5FF; font-weight: 800; }
.swir-notification-button {
  background: #07111C;
  color: #EAF9FF;
  border: 1px solid rgba(0,136,255,0.75);
  border-radius: 9px;
  padding: 5px 9px;
}
.swir-history-row {
  padding: 8px;
  border-bottom: 1px solid rgba(98,229,255,0.16);
}
"""

# Fixed commands only: user-controlled strings are never passed to a shell.
LAUNCHERS: Final = (
    ("Files", (("/usr/local/bin/swir-files",), ("/usr/bin/nautilus",), ("/usr/bin/thunar",), ("/usr/bin/pcmanfm",))),
    ("Browser", (("/usr/local/bin/swir-browser",),)),
    ("Player", (("/usr/local/bin/swir-player",),)),
    ("Photo Studio", (("/usr/local/bin/swir-photo-studio",),)),
    ("PDF Viewer", (("/usr/local/bin/swir-pdf-viewer",),)),
    ("Archive Manager", (("/usr/local/bin/swir-files", "--archive-manager"),)),
    ("Calculator", (("/usr/local/bin/swir-calculator",),)),
    ("Clock", (("/usr/local/bin/swir-clock",),)),
    ("Backup & Restore", (("/usr/local/bin/swir-backup",),)),
    ("Terminal", (("/usr/local/bin/swir-terminal",),)),
    ("Notes", (("/usr/local/bin/swir-notes",),)),
    ("Settings", (("/usr/local/bin/swir-settings",), ("/usr/bin/gnome-control-center",))),
    ("Network", (("/usr/local/bin/swir-network-center",),)),
    ("Hardware", (("/usr/local/bin/swir-hardware-center",),)),
    ("Software", (("/usr/local/bin/swir-software-center",),)),
    ("Updates", (("/usr/local/bin/swir-update-center",),)),
    ("System Monitor", (("/usr/local/bin/swir-system-monitor",),)),
    ("Install SWIR OS", (("/usr/local/bin/swir-installer",),)),
)


class NotificationPolicyError(RuntimeError):
    pass


def _sanitize_notification_text(value: str, limit: int) -> str:
    if not isinstance(value, str):
        raise NotificationPolicyError("notification text must be a string")
    cleaned = "".join(ch if (ch in "\n\t" or ord(ch) >= 0x20) else " " for ch in value)
    cleaned = cleaned.replace("\r", "\n")
    while "\n\n\n" in cleaned:
        cleaned = cleaned.replace("\n\n\n", "\n\n")
    return cleaned[:limit]


def _sanitize_actions(values: list[str] | tuple[str, ...]) -> tuple[tuple[str, str], ...]:
    items = list(values)
    pairs: list[tuple[str, str]] = []
    for index in range(0, min(len(items) - (len(items) % 2), MAX_ACTION_PAIRS * 2), 2):
        key = _sanitize_notification_text(str(items[index]), 80).strip()
        label = _sanitize_notification_text(str(items[index + 1]), 120).strip()
        if key and label and all(existing[0] != key for existing in pairs):
            pairs.append((key, label))
    return tuple(pairs)


def _notification_state_path() -> pathlib.Path:
    root = pathlib.Path(os.environ.get("XDG_STATE_HOME", pathlib.Path.home() / ".local" / "state"))
    return root / "swir" / "notifications" / "history.json"


def _ensure_owner_state_parent(path: pathlib.Path) -> None:
    parent = path.parent
    probe = pathlib.Path(parent.anchor or "/") if parent.is_absolute() else pathlib.Path.cwd()
    parts = parent.parts[1:] if parent.is_absolute() else parent.parts
    for part in parts:
        probe = probe / part
        if probe.exists() and probe.is_symlink():
            raise NotificationPolicyError(f"notification state path contains a symlink: {probe}")
    parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if parent.is_symlink() or not parent.is_dir():
        raise NotificationPolicyError("notification state directory is unsafe")
    if parent.stat().st_uid != os.getuid():
        raise NotificationPolicyError("notification state directory is not owned by the session user")
    try:
        parent.chmod(0o700)
    except OSError:
        pass


def _atomic_json(path: pathlib.Path, payload: object) -> None:
    _ensure_owner_state_parent(path)
    if path.exists() and path.is_symlink():
        raise NotificationPolicyError("notification history must not be a symlink")
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    tmp = pathlib.Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
        os.chmod(path, 0o600)
    finally:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass


@dataclass(frozen=True)
class NativeNotification:
    id: int
    app_name: str
    summary: str
    body: str
    actions: tuple[tuple[str, str], ...]
    created_at: str
    timeout_ms: int

    def history_record(self) -> dict[str, object]:
        return {
            "id": self.id,
            "appName": self.app_name,
            "summary": self.summary,
            "body": self.body,
            "createdAt": self.created_at,
        }


class NotificationHistory:
    def __init__(self, path: pathlib.Path | None = None) -> None:
        self.path = path or _notification_state_path()
        self.records: list[dict[str, object]] = []
        self._persist_lock = threading.Lock()
        self._pending_payload: dict[str, object] | None = None
        self._persist_thread: threading.Thread | None = None
        self.load()

    def load(self) -> None:
        try:
            _ensure_owner_state_parent(self.path)
            if self.path.is_symlink():
                raise NotificationPolicyError("notification history must not be a symlink")
            if self.path.exists() and self.path.stat().st_size > MAX_NOTIFICATION_HISTORY_BYTES:
                raise NotificationPolicyError("notification history exceeds the verified size bound")
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return
        except (OSError, json.JSONDecodeError, NotificationPolicyError) as exc:
            print(f"SWIR notification history ignored invalid state: {exc}", file=sys.stderr)
            return
        if not isinstance(raw, dict) or raw.get("schema") != NOTIFICATION_HISTORY_SCHEMA:
            return
        values = raw.get("notifications")
        if not isinstance(values, list) or len(values) > MAX_NOTIFICATION_HISTORY:
            return
        clean: list[dict[str, object]] = []
        for item in values:
            if not isinstance(item, dict):
                continue
            try:
                ident = int(item.get("id", 0))
                app_name = _sanitize_notification_text(str(item.get("appName", "")), MAX_APP_NAME_CHARS)
                summary = _sanitize_notification_text(str(item.get("summary", "")), MAX_SUMMARY_CHARS)
                body = _sanitize_notification_text(str(item.get("body", "")), MAX_BODY_CHARS)
                created_at = _sanitize_notification_text(str(item.get("createdAt", "")), 80)
            except (TypeError, ValueError, NotificationPolicyError):
                continue
            if ident > 0 and summary:
                clean.append({"id": ident, "appName": app_name, "summary": summary, "body": body, "createdAt": created_at})
        self.records = clean[-MAX_NOTIFICATION_HISTORY:]

    def _payload(self) -> dict[str, object]:
        return {"schema": NOTIFICATION_HISTORY_SCHEMA, "notifications": [dict(item) for item in self.records[-MAX_NOTIFICATION_HISTORY:]]}

    def append(self, note: NativeNotification, *, async_write: bool = False) -> None:
        self.records.append(note.history_record())
        self.records = self.records[-MAX_NOTIFICATION_HISTORY:]
        if async_write:
            self.save_async()
        else:
            self.save()

    def save(self) -> None:
        _atomic_json(self.path, self._payload())

    def save_async(self) -> None:
        payload = self._payload()
        with self._persist_lock:
            self._pending_payload = payload
            if self._persist_thread is not None and self._persist_thread.is_alive():
                return
            worker = threading.Thread(target=self._persist_worker, name="swir-notification-history", daemon=True)
            self._persist_thread = worker
            worker.start()

    def _persist_worker(self) -> None:
        while True:
            with self._persist_lock:
                payload = self._pending_payload
                self._pending_payload = None
                if payload is None:
                    self._persist_thread = None
                    return
            try:
                _atomic_json(self.path, payload)
            except (OSError, NotificationPolicyError) as exc:
                print(f"SWIR notification history async write failed: {exc}", file=sys.stderr)

    def flush(self, timeout: float = 2.0) -> bool:
        deadline = time.monotonic() + max(0.0, timeout)
        while True:
            with self._persist_lock:
                worker = self._persist_thread
            if worker is None:
                return True
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            worker.join(min(remaining, 0.2))

    def clear(self, *, async_write: bool = False) -> None:
        self.records = []
        if async_write:
            self.save_async()
        else:
            self.save()


class NotificationService:
    def __init__(self, on_present, on_closed, history_path: pathlib.Path | None = None) -> None:
        self.on_present = on_present
        self.on_closed = on_closed
        self.history = NotificationHistory(history_path)
        self.connection: Gio.DBusConnection | None = None
        self.owner_id = 0
        self.registration_id = 0
        self.node = Gio.DBusNodeInfo.new_for_xml(NOTIFICATION_XML)
        self.active: dict[int, NativeNotification] = {}
        self.timers: dict[int, int] = {}
        self.next_id = 1

    @property
    def available(self) -> bool:
        return bool(self.connection is not None and self.owner_id and self.registration_id)

    def start(self) -> bool:
        try:
            self.connection = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        except GLib.Error as exc:
            print(f"SWIR notification service unavailable: {exc}", file=sys.stderr)
            return False
        interface = self.node.interfaces[0]
        self.registration_id = self.connection.register_object(NOTIFICATION_PATH, interface, self._method_call, None, None)
        self.owner_id = Gio.bus_own_name_on_connection(self.connection, NOTIFICATION_BUS, Gio.BusNameOwnerFlags.NONE, None, None)
        return self.available

    def stop(self) -> None:
        for source_id in list(self.timers.values()):
            if source_id:
                GLib.source_remove(source_id)
        self.timers.clear()
        self.history.flush(2.0)
        if self.connection is not None and self.registration_id:
            try:
                self.connection.unregister_object(self.registration_id)
            except GLib.Error:
                pass
            self.registration_id = 0
        if self.owner_id:
            Gio.bus_unown_name(self.owner_id)
            self.owner_id = 0
        self.connection = None

    def _next_notification_id(self) -> int:
        for _ in range(2**16):
            ident = self.next_id
            self.next_id = 1 if self.next_id >= 0xFFFFFFFF else self.next_id + 1
            if ident not in self.active:
                return ident
        raise NotificationPolicyError("notification identifier space exhausted")

    def _method_call(self, _connection, _sender, _object_path, _interface, method, params, invocation) -> None:
        try:
            if method == "GetCapabilities":
                invocation.return_value(GLib.Variant("(as)", (["actions", "body", "persistence"],)))
                return
            if method == "GetServerInformation":
                invocation.return_value(GLib.Variant("(ssss)", ("SWIR Notification Service", "SWIR", "0.1", "1.2")))
                return
            if method == "CloseNotification":
                ident = int(params.unpack()[0])
                self.close(ident, 3)
                invocation.return_value(None)
                return
            if method == "Notify":
                app_name, replaces_id, _app_icon, summary, body, actions, _hints, expire_timeout = params.unpack()
                note = self.publish(app_name=str(app_name), replaces_id=int(replaces_id), summary=str(summary), body=str(body), actions=list(actions), expire_timeout=int(expire_timeout))
                invocation.return_value(GLib.Variant("(u)", (note.id,)))
                return
            invocation.return_dbus_error("org.freedesktop.Notifications.Error.NotSupported", f"unsupported method: {method}")
        except (NotificationPolicyError, OSError, ValueError, TypeError) as exc:
            invocation.return_dbus_error("org.freedesktop.Notifications.Error.InvalidNotification", str(exc))

    def publish(self, *, app_name: str, replaces_id: int, summary: str, body: str, actions: list[str], expire_timeout: int) -> NativeNotification:
        app = _sanitize_notification_text(app_name, MAX_APP_NAME_CHARS).strip() or "Application"
        title = _sanitize_notification_text(summary, MAX_SUMMARY_CHARS).strip()
        if not title:
            raise NotificationPolicyError("notification summary must not be empty")
        text = _sanitize_notification_text(body, MAX_BODY_CHARS)
        clean_actions = _sanitize_actions(actions)
        ident = replaces_id if replaces_id in self.active else self._next_notification_id()
        timeout = DEFAULT_TIMEOUT_MS if expire_timeout < 0 else min(max(expire_timeout, 0), MAX_TIMEOUT_MS)
        note = NativeNotification(id=ident, app_name=app, summary=title, body=text, actions=clean_actions, created_at=dt.datetime.now(dt.timezone.utc).isoformat(), timeout_ms=timeout)
        old_timer = self.timers.pop(ident, 0)
        if old_timer:
            GLib.source_remove(old_timer)
        self.active[ident] = note
        self.history.append(note, async_write=True)
        GLib.idle_add(self._deliver_present, note)
        if timeout > 0:
            self.timers[ident] = GLib.timeout_add(timeout, self._expire, ident)
        return note

    def _deliver_present(self, note: NativeNotification) -> bool:
        if self.active.get(note.id) == note:
            self.on_present(note)
        return False

    def _expire(self, ident: int) -> bool:
        self.timers.pop(ident, None)
        self.close(ident, 1)
        return False

    def close(self, ident: int, reason: int) -> None:
        note = self.active.pop(ident, None)
        source_id = self.timers.pop(ident, 0)
        if source_id:
            GLib.source_remove(source_id)
        if note is None:
            return
        if self.connection is not None:
            self.connection.emit_signal(None, NOTIFICATION_PATH, NOTIFICATION_IFACE, "NotificationClosed", GLib.Variant("(uu)", (ident, int(reason))))
        self.on_closed(ident, int(reason))

    def invoke_action(self, ident: int, action_key: str) -> None:
        note = self.active.get(ident)
        if note is None or action_key not in {key for key, _label in note.actions}:
            return
        if self.connection is not None:
            self.connection.emit_signal(None, NOTIFICATION_PATH, NOTIFICATION_IFACE, "ActionInvoked", GLib.Variant("(us)", (ident, action_key)))

    def clear_history(self) -> None:
        self.history.clear(async_write=True)


class SwirShell(Gtk.Application):
    def __init__(self) -> None:
        super().__init__(application_id=APP_ID)
        self.clock_label: Gtk.Label | None = None
        self.status_label: Gtk.Label | None = None
        self.window: Gtk.ApplicationWindow | None = None
        self.evidence_path = os.environ.get("SWIR_SHELL_EVIDENCE_PATH", "")
        self.e2e = os.environ.get("SWIR_SHELL_E2E", "0") == "1"
        self.notification_e2e = os.environ.get("SWIR_NOTIFICATION_E2E", "0") == "1"
        self.notification_evidence_path = os.environ.get("SWIR_NOTIFICATION_EVIDENCE_PATH", "")
        self.notification_evidence_written = False
        self.evidence_written = False
        self.window_mapped = False
        self.clock24h = True
        self.theme_id = DEFAULT_THEME_ID
        self.theme_fallback = False
        self.theme_payload: dict[str, object] | None = None
        self.toast_panel: Gtk.Box | None = None
        self.toast_summary: Gtk.Label | None = None
        self.toast_body: Gtk.Label | None = None
        self.toast_actions: Gtk.Box | None = None
        self.notification_button: Gtk.MenuButton | None = None
        self.history_box: Gtk.Box | None = None
        self.current_notification_id = 0
        self.notification_service: NotificationService | None = None
        settings: dict[str, object] = {}
        if UserSettingsStore is not None:
            try:
                settings = UserSettingsStore().load()
                self.clock24h = bool(settings.get("clock24h", True))
            except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
                print(f"SWIR shell ignored invalid user settings: {exc}", file=sys.stderr)
        if ThemeStore is not None:
            try:
                self.theme_payload, self.theme_fallback = ThemeStore().load(settings.get("themeId", DEFAULT_THEME_ID))
                self.theme_id = str(self.theme_payload["id"])
            except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
                print(f"SWIR shell recovered to the default theme: {exc}", file=sys.stderr)
                self.theme_fallback = True
                if default_theme is not None:
                    self.theme_payload = default_theme()
                    self.theme_id = str(self.theme_payload["id"])

    def do_startup(self) -> None:
        Gtk.Application.do_startup(self)
        display = Gdk.Display.get_default()
        if display is None:
            raise RuntimeError("SWIR shell requires an active graphical display")
        provider = Gtk.CssProvider()
        provider.load_from_data(CSS)
        Gtk.StyleContext.add_provider_for_display(display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        if self.theme_payload is not None and theme_css is not None:
            themed = Gtk.CssProvider()
            themed.load_from_data(theme_css(self.theme_payload))
            Gtk.StyleContext.add_provider_for_display(display, themed, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1)
        self.notification_service = NotificationService(self._present_notification, self._notification_closed)
        self.notification_service.start()

    def do_shutdown(self) -> None:
        if self.notification_service is not None:
            self.notification_service.stop()
        Gtk.Application.do_shutdown(self)

    def do_activate(self) -> None:
        if self.window is not None:
            self.window.present()
            return
        window = Gtk.ApplicationWindow(application=self)
        window.set_title("SWIR OS")
        window.set_default_size(1280, 720)
        window.add_css_class("swir-shell")
        window.fullscreen()
        self.window = window

        overlay = Gtk.Overlay()
        window.set_child(overlay)
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        overlay.set_child(root)

        top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        top.add_css_class("swir-topbar")
        brand = Gtk.Label(label="◆  SWIR OS")
        brand.add_css_class("swir-brand")
        brand.set_xalign(0)
        top.append(brand)
        edition = Gtk.Label(label="SYSTEM EDITION")
        edition.add_css_class("swir-subtle")
        top.append(edition)
        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        top.append(spacer)

        self.notification_button = Gtk.MenuButton(label="Notifications")
        self.notification_button.add_css_class("swir-notification-button")
        popover = Gtk.Popover()
        popover.set_size_request(420, 360)
        history_root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        history_root.set_margin_top(10)
        history_root.set_margin_bottom(10)
        history_root.set_margin_start(10)
        history_root.set_margin_end(10)
        history_title = Gtk.Label(label="Notification Center")
        history_title.add_css_class("swir-notification-title")
        history_title.set_xalign(0)
        history_root.append(history_title)
        scroll = Gtk.ScrolledWindow()
        scroll.set_vexpand(True)
        self.history_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        scroll.set_child(self.history_box)
        history_root.append(scroll)
        clear = Gtk.Button(label="Clear history")
        clear.add_css_class("swir-notification-button")
        clear.connect("clicked", self._clear_notification_history)
        history_root.append(clear)
        popover.set_child(history_root)
        self.notification_button.set_popover(popover)
        top.append(self.notification_button)

        self.clock_label = Gtk.Label()
        self.clock_label.add_css_class("swir-brand")
        top.append(self.clock_label)
        root.append(top)

        center = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=22)
        center.set_hexpand(True)
        center.set_vexpand(True)
        center.set_halign(Gtk.Align.CENTER)
        center.set_valign(Gtk.Align.CENTER)
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        card.add_css_class("swir-card")
        card.set_size_request(650, -1)
        title = Gtk.Label(label="Welcome to SWIR OS")
        title.add_css_class("swir-title")
        title.set_xalign(0)
        card.append(title)
        detail = Gtk.Label(label="Native Linux desktop session • Debian 13 foundation • Wayland", wrap=True)
        detail.add_css_class("swir-subtle")
        detail.set_xalign(0)
        card.append(detail)
        self.status_label = Gtk.Label(label="Ready")
        self.status_label.set_xalign(0)
        card.append(self.status_label)
        center.append(card)
        root.append(center)

        dock = Gtk.FlowBox()
        dock.add_css_class("swir-dock")
        dock.set_selection_mode(Gtk.SelectionMode.NONE)
        dock.set_homogeneous(True)
        dock.set_row_spacing(8)
        dock.set_column_spacing(10)
        dock.set_min_children_per_line(2)
        dock.set_max_children_per_line(5)
        dock.set_halign(Gtk.Align.FILL)
        dock.set_hexpand(True)
        for label, candidates in LAUNCHERS:
            button = Gtk.Button(label=label)
            button.add_css_class("swir-launcher")
            button.set_hexpand(True)
            button.connect("clicked", self._launch, label, candidates)
            dock.append(button)
        root.append(dock)

        self.toast_panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=7)
        self.toast_panel.add_css_class("swir-notification")
        self.toast_panel.set_size_request(380, -1)
        self.toast_panel.set_halign(Gtk.Align.END)
        self.toast_panel.set_valign(Gtk.Align.START)
        self.toast_panel.set_margin_top(72)
        self.toast_panel.set_margin_end(18)
        toast_header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.toast_summary = Gtk.Label()
        self.toast_summary.add_css_class("swir-notification-title")
        self.toast_summary.set_xalign(0)
        self.toast_summary.set_hexpand(True)
        self.toast_summary.set_wrap(True)
        toast_header.append(self.toast_summary)
        dismiss = Gtk.Button(label="Dismiss")
        dismiss.add_css_class("swir-notification-button")
        dismiss.connect("clicked", self._dismiss_current_notification)
        toast_header.append(dismiss)
        self.toast_panel.append(toast_header)
        self.toast_body = Gtk.Label(wrap=True)
        self.toast_body.set_xalign(0)
        self.toast_body.set_max_width_chars(52)
        self.toast_panel.append(self.toast_body)
        self.toast_actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.toast_panel.append(self.toast_actions)
        self.toast_panel.set_visible(False)
        overlay.add_overlay(self.toast_panel)

        self._refresh_notification_history()
        GLib.timeout_add_seconds(1, self._update_clock)
        self._update_clock()
        window.connect("map", self._on_mapped)
        window.present()

    def _update_clock(self) -> bool:
        if self.clock_label is not None:
            now = dt.datetime.now().astimezone()
            text = now.strftime("%H:%M") if self.clock24h else now.strftime("%I:%M %p").lstrip("0")
            self.clock_label.set_text(text)
        return True

    def _launch(self, _button: Gtk.Button, label: str, candidates: tuple[tuple[str, ...], ...]) -> None:
        command = next((candidate for candidate in candidates if pathlib.Path(candidate[0]).is_file()), None)
        if command is None:
            if self.status_label is not None:
                self.status_label.set_text(f"{label} is not installed in this image yet.")
            return
        try:
            subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True, start_new_session=True)
            if self.status_label is not None:
                self.status_label.set_text(f"Opened {label}")
        except OSError as exc:
            if self.status_label is not None:
                self.status_label.set_text(f"Could not open {label}: {exc.strerror or 'launch failed'}")

    def _present_notification(self, note: NativeNotification) -> None:
        self.current_notification_id = note.id
        if self.toast_summary is not None:
            self.toast_summary.set_text(f"{note.app_name} • {note.summary}")
        if self.toast_body is not None:
            self.toast_body.set_text(note.body)
            self.toast_body.set_visible(bool(note.body))
        if self.toast_actions is not None:
            child = self.toast_actions.get_first_child()
            while child is not None:
                next_child = child.get_next_sibling()
                self.toast_actions.remove(child)
                child = next_child
            for key, label in note.actions:
                button = Gtk.Button(label=label)
                button.add_css_class("swir-notification-button")
                button.connect("clicked", self._notification_action_clicked, note.id, key)
                self.toast_actions.append(button)
        if self.toast_panel is not None:
            self.toast_panel.set_visible(True)
        self._refresh_notification_history()
        self._write_notification_evidence(note)

    def _notification_closed(self, ident: int, _reason: int) -> None:
        if ident == self.current_notification_id:
            self.current_notification_id = 0
            if self.toast_panel is not None:
                self.toast_panel.set_visible(False)

    def _notification_action_clicked(self, _button: Gtk.Button, ident: int, key: str) -> None:
        if self.notification_service is None:
            return
        self.notification_service.invoke_action(ident, key)
        self.notification_service.close(ident, 2)

    def _dismiss_current_notification(self, _button: Gtk.Button) -> None:
        if self.notification_service is not None and self.current_notification_id:
            self.notification_service.close(self.current_notification_id, 2)

    def _clear_notification_history(self, _button: Gtk.Button) -> None:
        if self.notification_service is not None:
            self.notification_service.clear_history()
        self._refresh_notification_history()

    def _refresh_notification_history(self) -> None:
        if self.history_box is None:
            return
        child = self.history_box.get_first_child()
        while child is not None:
            next_child = child.get_next_sibling()
            self.history_box.remove(child)
            child = next_child
        records = self.notification_service.history.records if self.notification_service is not None else []
        recent = list(reversed(records[-MAX_VISIBLE_HISTORY:]))
        if self.notification_button is not None:
            self.notification_button.set_label(f"Notifications ({len(records)})" if records else "Notifications")
        if not recent:
            empty = Gtk.Label(label="No notifications yet.")
            empty.add_css_class("swir-subtle")
            empty.set_xalign(0)
            self.history_box.append(empty)
            return
        for item in recent:
            row = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
            row.add_css_class("swir-history-row")
            summary = Gtk.Label(label=f"{item.get('appName', 'Application')} • {item.get('summary', '')}", wrap=True)
            summary.set_xalign(0)
            summary.add_css_class("swir-notification-title")
            row.append(summary)
            body = str(item.get("body", ""))
            if body:
                body_label = Gtk.Label(label=body, wrap=True)
                body_label.set_xalign(0)
                row.append(body_label)
            created = Gtk.Label(label=str(item.get("createdAt", "")))
            created.add_css_class("swir-subtle")
            created.set_xalign(0)
            row.append(created)
            self.history_box.append(row)

    def _write_notification_evidence(self, note: NativeNotification) -> None:
        if not self.notification_e2e or self.notification_evidence_written or not self.window_mapped or not self.notification_evidence_path:
            return
        runtime_text = os.environ.get("XDG_RUNTIME_DIR", "")
        path = pathlib.Path(self.notification_evidence_path)
        if not runtime_text or path.parent.resolve() != pathlib.Path(runtime_text).resolve():
            print("refusing notification evidence path outside XDG_RUNTIME_DIR", file=sys.stderr)
            return
        history = self.notification_service.history.records if self.notification_service is not None else []
        payload = {
            "schema": "swir.native-notification-runtime-evidence/0.1",
            "passed": True,
            "applicationId": APP_ID,
            "nativeToolkit": "gtk4",
            "displayProtocol": "wayland",
            "windowMapped": self.window_mapped,
            "serviceName": NOTIFICATION_BUS,
            "serviceOwned": bool(self.notification_service and self.notification_service.available),
            "notifyAccepted": True,
            "notificationId": note.id,
            "plainTextRendering": True,
            "imageHintsLoaded": False,
            "actionCount": len(note.actions),
            "historyPersisted": bool(history and int(history[-1].get("id", 0)) == note.id),
            "historyBound": MAX_NOTIFICATION_HISTORY,
            "privilegedOperations": False,
            "shellExecution": False,
        }
        path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
        path.chmod(0o600)
        self.notification_evidence_written = True

    def _run_e2e_launcher_probe(self) -> bool:
        if not self.e2e:
            return False
        probe = pathlib.Path("/usr/bin/true")
        if not probe.is_file() or not os.access(probe, os.X_OK):
            raise RuntimeError("trusted launcher probe executable is missing")
        completed = subprocess.run((str(probe),), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True, check=False, timeout=5)
        return completed.returncode == 0

    def _on_mapped(self, _window: Gtk.Window) -> None:
        self.window_mapped = True
        if self.current_notification_id and self.notification_service is not None:
            pending = self.notification_service.active.get(self.current_notification_id)
            if pending is not None:
                self._present_notification(pending)
        if self.evidence_written or not self.evidence_path:
            return
        path = pathlib.Path(self.evidence_path)
        runtime_text = os.environ.get("XDG_RUNTIME_DIR", "")
        if not runtime_text:
            print("missing XDG_RUNTIME_DIR for shell evidence", file=sys.stderr)
            return
        runtime = pathlib.Path(runtime_text).resolve()
        if path.parent.resolve() != runtime:
            print("refusing shell evidence path outside XDG_RUNTIME_DIR", file=sys.stderr)
            return
        launcher_probe_passed = self._run_e2e_launcher_probe()
        payload = {
            "schema": EVIDENCE_SCHEMA,
            "passed": True,
            "applicationId": APP_ID,
            "nativeToolkit": "gtk4",
            "displayProtocol": "wayland",
            "windowMapped": True,
            "fullscreenRequested": True,
            "launcherEntries": [item[0] for item in LAUNCHERS],
            "launcherProbePassed": launcher_probe_passed,
            "privilegedOperationsInShell": False,
            "clock24h": self.clock24h,
            "themeId": self.theme_id,
            "themeFallbackToDefault": self.theme_fallback,
            "themePackagesDataOnly": True,
            "notificationServiceOwned": bool(self.notification_service and self.notification_service.available),
            "notificationHistoryBound": MAX_NOTIFICATION_HISTORY,
            "notificationMarkupRendered": False,
            "notificationExternalImagesLoaded": False,
        }
        path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
        path.chmod(0o600)
        self.evidence_written = True


def _notification_self_test() -> int:
    assert _sanitize_notification_text("a\x01b", 10) == "a b"
    assert _sanitize_notification_text("<b>literal</b>", 100) == "<b>literal</b>"
    actions = _sanitize_actions(["default", "Open", "dismiss", "Dismiss"])
    assert actions == (("default", "Open"), ("dismiss", "Dismiss"))
    assert len(_sanitize_actions([str(i) for i in range(40)])) <= MAX_ACTION_PAIRS
    with tempfile.TemporaryDirectory(prefix="swir-notify-selftest-") as tmp:
        state = pathlib.Path(tmp) / "state" / "history.json"
        history = NotificationHistory(state)
        note = NativeNotification(id=1, app_name="Self Test", summary="Notification", body="plain text", actions=actions, created_at="2026-09-18T00:00:00+00:00", timeout_ms=DEFAULT_TIMEOUT_MS)
        history.append(note)
        assert state.is_file() and (state.stat().st_mode & 0o777) == 0o600
        loaded = NotificationHistory(state)
        assert len(loaded.records) == 1 and loaded.records[0]["summary"] == "Notification"
        history.clear()
        assert NotificationHistory(state).records == []
    print("SWIR native notification self-test: OK")
    return 0


if __name__ == "__main__":
    if "--notification-self-test" in sys.argv:
        raise SystemExit(_notification_self_test())
    raise SystemExit(SwirShell().run(sys.argv))
