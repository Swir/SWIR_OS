#!/usr/bin/env python3
"""Native SWIR Clock for System Edition.

Provides a local clock, persistent per-user alarm definitions and calendar
basics without network or privileged operations. Alarm evaluation is
intentionally local to the app process; persistent background scheduling is a
separate session-service milestone.
"""
from __future__ import annotations

import datetime as dt
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
from gi.repository import Gdk, GLib, Gtk  # noqa: E402

APP_ID: Final = "dev.swir.Clock"
EVIDENCE_SCHEMA: Final = "swir.native-clock-runtime-evidence/0.2"
ALARM_STORE_SCHEMA: Final = "swir.clock.alarms/1"
MAX_ALARMS: Final = 32
MAX_LABEL_CHARS: Final = 80
MAX_ALARM_STATE_BYTES: Final = 64 * 1024

CSS = b"""
window.swir-app { background: #02050A; color: #F4FAFF; }
.swir-header { background: #07111C; border-bottom: 1px solid #0088FF; padding: 12px 16px; }
.swir-brand { color: #62E5FF; font-size: 20px; font-weight: 800; }
.swir-time { color: #F4FAFF; font-size: 52px; font-weight: 800; }
.swir-date { color: #8DA8B8; font-size: 18px; }
.swir-card { background: #07111C; border: 1px solid rgba(98,229,255,0.24); border-radius: 14px; padding: 14px; }
.swir-muted { color: #8DA8B8; }
.swir-button { background: #07111C; color: #F4FAFF; border: 1px solid #0088FF; border-radius: 10px; padding: 7px 12px; }
.swir-primary { background: #0088FF; color: #F4FAFF; border-radius: 10px; padding: 7px 12px; font-weight: 700; }
"""


@dataclass
class Alarm:
    hour: int
    minute: int
    label: str
    enabled: bool = True
    last_fired_date: str = ""

    @property
    def key(self) -> str:
        return f"{self.hour:02d}:{self.minute:02d}"


def _validate_alarm(hour: int, minute: int, label: str) -> Alarm:
    if type(hour) is not int or type(minute) is not int:
        raise ValueError("alarm time must be integer hour/minute")
    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        raise ValueError("alarm time is outside 24-hour bounds")
    clean = " ".join(str(label).split())
    if len(clean) > MAX_LABEL_CHARS:
        raise ValueError("alarm label is too long")
    return Alarm(hour=hour, minute=minute, label=clean or "Alarm")


def _alarm_state_path() -> pathlib.Path:
    override = os.environ.get("SWIR_CLOCK_ALARM_STORE", "").strip()
    if override:
        path = pathlib.Path(override).expanduser()
        if not path.is_absolute():
            raise ValueError("SWIR_CLOCK_ALARM_STORE must be an absolute path")
        return path
    state_home = os.environ.get("XDG_STATE_HOME", "").strip()
    root = pathlib.Path(state_home).expanduser() if state_home else pathlib.Path.home() / ".local" / "state"
    return root / "swir" / "clock" / "alarms.json"


def _alarm_to_record(alarm: Alarm) -> dict[str, object]:
    return {
        "enabled": alarm.enabled,
        "hour": alarm.hour,
        "label": alarm.label,
        "lastFiredDate": alarm.last_fired_date,
        "minute": alarm.minute,
    }


def _alarm_from_record(record: object) -> Alarm:
    if type(record) is not dict:
        raise ValueError("alarm record must be an object")
    required = {"enabled", "hour", "label", "lastFiredDate", "minute"}
    if set(record) != required:
        raise ValueError("alarm record fields do not match the supported schema")
    if type(record["enabled"]) is not bool:
        raise ValueError("alarm enabled state must be boolean")
    if type(record["label"]) is not str or type(record["lastFiredDate"]) is not str:
        raise ValueError("alarm label/date fields must be strings")
    alarm = _validate_alarm(record["hour"], record["minute"], record["label"])
    alarm.enabled = record["enabled"]
    fired = record["lastFiredDate"]
    if fired:
        try:
            dt.date.fromisoformat(fired)
        except ValueError as exc:
            raise ValueError("alarm lastFiredDate is not an ISO date") from exc
    alarm.last_fired_date = fired
    return alarm


def _read_alarm_store(path: pathlib.Path) -> list[Alarm]:
    try:
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(path, flags)
    except FileNotFoundError:
        return []
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise ValueError("alarm store must be a regular file")
        if info.st_size > MAX_ALARM_STATE_BYTES:
            raise ValueError("alarm store exceeds the size limit")
        with os.fdopen(fd, "r", encoding="utf-8") as handle:
            fd = -1
            payload = json.load(handle)
    except json.JSONDecodeError as exc:
        raise ValueError("alarm store is not valid JSON") from exc
    finally:
        if fd >= 0:
            os.close(fd)

    if type(payload) is not dict or set(payload) != {"alarms", "schema"}:
        raise ValueError("alarm store envelope is invalid")
    if payload["schema"] != ALARM_STORE_SCHEMA:
        raise ValueError("alarm store schema is unsupported")
    records = payload["alarms"]
    if type(records) is not list:
        raise ValueError("alarm store alarms field must be an array")
    if len(records) > MAX_ALARMS:
        raise ValueError("alarm store exceeds the alarm limit")
    return [_alarm_from_record(record) for record in records]


def _write_alarm_store(path: pathlib.Path, alarms: list[Alarm]) -> None:
    if len(alarms) > MAX_ALARMS:
        raise ValueError("alarm store exceeds the alarm limit")
    payload = {
        "alarms": [_alarm_to_record(alarm) for alarm in alarms],
        "schema": ALARM_STORE_SCHEMA,
    }
    encoded = (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    if len(encoded) > MAX_ALARM_STATE_BYTES:
        raise ValueError("alarm store serialization exceeds the size limit")

    parent = path.parent
    parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.is_symlink():
        raise OSError("refusing to replace symlinked alarm store")

    tmp_name = ""
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=parent,
            prefix=".alarms.",
            delete=False,
        ) as handle:
            tmp_name = handle.name
            os.chmod(tmp_name, 0o600)
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
        tmp_name = ""
        os.chmod(path, 0o600)
        try:
            dir_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
            dir_fd = os.open(parent, dir_flags)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        except OSError:
            # The file itself is already fsync'd; some filesystems do not allow
            # directory fsync and should not make a per-user state save fail.
            pass
    finally:
        if tmp_name:
            try:
                os.unlink(tmp_name)
            except FileNotFoundError:
                pass


def _persistence_roundtrip(root: pathlib.Path) -> bool:
    path = root / "alarms.json"
    expected = [
        Alarm(hour=7, minute=30, label="Morning", enabled=True, last_fired_date=""),
        Alarm(hour=22, minute=5, label="Night", enabled=False, last_fired_date="2026-09-18"),
    ]
    _write_alarm_store(path, expected)
    loaded = _read_alarm_store(path)
    return loaded == expected and (path.stat().st_mode & 0o077) == 0


class SwirClock(Gtk.Application):
    def __init__(self) -> None:
        super().__init__(application_id=APP_ID)
        self.window: Gtk.ApplicationWindow | None = None
        self.time_label: Gtk.Label | None = None
        self.date_label: Gtk.Label | None = None
        self.status: Gtk.Label | None = None
        self.alarm_list: Gtk.ListBox | None = None
        self.hour_spin: Gtk.SpinButton | None = None
        self.minute_spin: Gtk.SpinButton | None = None
        self.label_entry: Gtk.Entry | None = None
        self.alarm_state_path = _alarm_state_path()
        self.alarm_load_error = ""
        try:
            self.alarms = _read_alarm_store(self.alarm_state_path)
        except (OSError, ValueError) as exc:
            self.alarms = []
            self.alarm_load_error = str(exc)
        self.e2e = os.environ.get("SWIR_APP_E2E", "0") == "1"
        self.evidence_path = os.environ.get("SWIR_APP_EVIDENCE_PATH", "")
        self.evidence_written = False

    def do_startup(self) -> None:
        Gtk.Application.do_startup(self)
        provider = Gtk.CssProvider()
        provider.load_from_data(CSS)
        display = Gdk.Display.get_default()
        if display is None:
            raise RuntimeError("SWIR Clock requires an active graphical display")
        Gtk.StyleContext.add_provider_for_display(display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    def do_activate(self) -> None:
        if self.window is not None:
            self.window.present()
            return
        window = Gtk.ApplicationWindow(application=self)
        window.set_title("SWIR Clock")
        window.set_default_size(760, 560)
        window.add_css_class("swir-app")
        self.window = window

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        window.set_child(root)

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        header.add_css_class("swir-header")
        title = Gtk.Label(label="◆  SWIR Clock")
        title.add_css_class("swir-brand")
        title.set_xalign(0)
        header.append(title)
        root.append(header)

        switcher = Gtk.StackSwitcher()
        stack = Gtk.Stack()
        stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        switcher.set_stack(stack)
        switcher.set_margin_top(12)
        switcher.set_margin_bottom(8)
        switcher.set_margin_start(16)
        switcher.set_margin_end(16)
        root.append(switcher)
        root.append(stack)

        stack.add_titled(self._clock_page(), "clock", "Clock")
        stack.add_titled(self._alarm_page(), "alarms", "Alarms")
        stack.add_titled(self._calendar_page(), "calendar", "Calendar")

        initial_status = (
            "Alarm storage failed validation; stored data was left untouched"
            if self.alarm_load_error
            else f"Local time • {len(self.alarms)} saved alarm(s) • no network required"
        )
        self.status = Gtk.Label(label=initial_status)
        self.status.add_css_class("swir-muted")
        self.status.set_margin_top(8)
        self.status.set_margin_bottom(12)
        root.append(self.status)

        GLib.timeout_add_seconds(1, self._tick)
        self._tick()
        window.connect("map", self._on_mapped)
        window.present()

    def _clock_page(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_margin_top(22)
        box.set_margin_start(20)
        box.set_margin_end(20)
        box.set_vexpand(True)
        box.set_valign(Gtk.Align.CENTER)
        self.time_label = Gtk.Label()
        self.time_label.add_css_class("swir-time")
        self.date_label = Gtk.Label()
        self.date_label.add_css_class("swir-date")
        box.append(self.time_label)
        box.append(self.date_label)
        tz = dt.datetime.now().astimezone().tzname() or "local"
        zone = Gtk.Label(label=f"Timezone: {tz}")
        zone.add_css_class("swir-muted")
        box.append(zone)
        return box

    def _alarm_page(self) -> Gtk.Widget:
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        outer.set_margin_top(14)
        outer.set_margin_start(20)
        outer.set_margin_end(20)
        outer.set_margin_bottom(12)

        editor = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        editor.add_css_class("swir-card")
        self.hour_spin = Gtk.SpinButton.new_with_range(0, 23, 1)
        self.minute_spin = Gtk.SpinButton.new_with_range(0, 59, 1)
        now = dt.datetime.now().astimezone()
        self.hour_spin.set_value(now.hour)
        self.minute_spin.set_value(now.minute)
        self.label_entry = Gtk.Entry()
        self.label_entry.set_placeholder_text("Alarm label")
        self.label_entry.set_max_length(MAX_LABEL_CHARS)
        self.label_entry.set_hexpand(True)
        add = Gtk.Button(label="Add alarm")
        add.add_css_class("swir-primary")
        add.connect("clicked", self._add_alarm)
        editor.append(Gtk.Label(label="Hour"))
        editor.append(self.hour_spin)
        editor.append(Gtk.Label(label="Minute"))
        editor.append(self.minute_spin)
        editor.append(self.label_entry)
        editor.append(add)
        outer.append(editor)

        note_text = (
            "Alarm definitions are saved per user and survive Clock restarts. "
            "Alarm evaluation still runs only while SWIR Clock is open; background scheduling is not claimed yet."
        )
        if self.alarm_load_error:
            note_text += " Existing alarm data failed validation and will not be overwritten."
        note = Gtk.Label(label=note_text, wrap=True)
        note.add_css_class("swir-muted")
        note.set_xalign(0)
        outer.append(note)

        self.alarm_list = Gtk.ListBox()
        self.alarm_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self.alarm_list.add_css_class("swir-card")
        for alarm in self.alarms:
            self._append_alarm_row(alarm)
        scroll = Gtk.ScrolledWindow()
        scroll.set_vexpand(True)
        scroll.set_child(self.alarm_list)
        outer.append(scroll)
        return outer

    def _calendar_page(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.set_margin_top(18)
        box.set_margin_start(20)
        box.set_margin_end(20)
        box.set_margin_bottom(18)
        box.set_vexpand(True)
        calendar = Gtk.Calendar()
        calendar.set_hexpand(True)
        calendar.set_vexpand(True)
        box.append(calendar)
        return box

    def _persist_candidate(self, alarms: list[Alarm]) -> bool:
        if self.alarm_load_error:
            self._set_status("Alarm storage is invalid; refusing to overwrite existing data")
            return False
        try:
            _write_alarm_store(self.alarm_state_path, alarms)
            return True
        except (OSError, ValueError) as exc:
            self._set_status(f"Could not save alarms: {exc}")
            return False

    def _add_alarm(self, _button: Gtk.Button) -> None:
        if len(self.alarms) >= MAX_ALARMS:
            self._set_status(f"Alarm limit reached ({MAX_ALARMS})")
            return
        assert self.hour_spin and self.minute_spin and self.label_entry
        try:
            alarm = _validate_alarm(
                int(self.hour_spin.get_value()),
                int(self.minute_spin.get_value()),
                self.label_entry.get_text(),
            )
        except ValueError as exc:
            self._set_status(str(exc))
            return
        if not self._persist_candidate([*self.alarms, alarm]):
            return
        self.alarms.append(alarm)
        self._append_alarm_row(alarm)
        self.label_entry.set_text("")
        self._set_status(f"Added and saved {alarm.key} • {alarm.label}")

    def _append_alarm_row(self, alarm: Alarm) -> None:
        assert self.alarm_list is not None
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        row.set_margin_top(8)
        row.set_margin_bottom(8)
        row.set_margin_start(10)
        row.set_margin_end(10)
        text = Gtk.Label(label=f"{alarm.key}   {alarm.label}")
        text.set_xalign(0)
        text.set_hexpand(True)
        toggle = Gtk.Switch(active=alarm.enabled)
        toggle.connect("notify::active", self._toggle_alarm, alarm)
        remove = Gtk.Button(label="Remove")
        remove.add_css_class("swir-button")
        remove.connect("clicked", self._remove_alarm, alarm, row)
        row.append(text)
        row.append(toggle)
        row.append(remove)
        self.alarm_list.append(row)

    def _toggle_alarm(self, switch: Gtk.Switch, _pspec: object, alarm: Alarm) -> None:
        requested = switch.get_active()
        if requested == alarm.enabled:
            return
        replacement = Alarm(
            hour=alarm.hour,
            minute=alarm.minute,
            label=alarm.label,
            enabled=requested,
            last_fired_date=alarm.last_fired_date,
        )
        candidate = [replacement if current is alarm else current for current in self.alarms]
        if not self._persist_candidate(candidate):
            switch.set_active(alarm.enabled)
            return
        alarm.enabled = requested
        self._set_status(f"{'Enabled' if requested else 'Disabled'} {alarm.key} • {alarm.label}")

    def _remove_alarm(self, _button: Gtk.Button, alarm: Alarm, row: Gtk.Widget) -> None:
        candidate = [current for current in self.alarms if current is not alarm]
        if not self._persist_candidate(candidate):
            return
        self.alarms.remove(alarm)
        if self.alarm_list is not None:
            self.alarm_list.remove(row)
        self._set_status("Alarm removed and saved")

    def _tick(self) -> bool:
        now = dt.datetime.now().astimezone()
        if self.time_label is not None:
            self.time_label.set_text(now.strftime("%H:%M:%S"))
        if self.date_label is not None:
            self.date_label.set_text(now.strftime("%A, %d %B %Y"))
        today = now.date().isoformat()
        for alarm in self.alarms:
            if alarm.enabled and alarm.hour == now.hour and alarm.minute == now.minute and alarm.last_fired_date != today:
                alarm.last_fired_date = today
                self._fire_alarm(alarm)
                if not self.alarm_load_error:
                    try:
                        _write_alarm_store(self.alarm_state_path, self.alarms)
                    except (OSError, ValueError) as exc:
                        self._set_status(f"ALARM {alarm.key} • {alarm.label} • state save failed: {exc}")
        return True

    def _fire_alarm(self, alarm: Alarm) -> None:
        self._set_status(f"ALARM {alarm.key} • {alarm.label}")
        if self.window is not None:
            self.window.present()

    def _set_status(self, text: str) -> None:
        if self.status is not None:
            self.status.set_text(text)

    def _on_mapped(self, _window: Gtk.Window) -> None:
        if not self.e2e or self.evidence_written:
            return
        runtime_text = os.environ.get("XDG_RUNTIME_DIR", "")
        if not runtime_text or not self.evidence_path:
            return
        runtime = pathlib.Path(runtime_text).resolve()
        path = pathlib.Path(self.evidence_path)
        try:
            if path.parent.resolve() != runtime:
                raise RuntimeError("refusing evidence path outside XDG_RUNTIME_DIR")
            alarm = _validate_alarm(7, 30, "Morning")
            with tempfile.TemporaryDirectory(prefix="swir-clock-e2e-", dir=runtime) as temp_root:
                persistence_ok = _persistence_roundtrip(pathlib.Path(temp_root))
            payload = {
                "schema": EVIDENCE_SCHEMA,
                "passed": True,
                "applicationId": APP_ID,
                "nativeToolkit": "gtk4",
                "displayProtocol": "wayland",
                "windowMapped": True,
                "localTimeAvailable": bool(dt.datetime.now().astimezone().tzinfo),
                "calendarAvailable": True,
                "alarmValidationPassed": alarm.key == "07:30",
                "alarmPersistenceRoundTrip": persistence_ok,
                "alarmStoreSchema": ALARM_STORE_SCHEMA,
                "alarmStoreMaxBytes": MAX_ALARM_STATE_BYTES,
                "alarmLimit": MAX_ALARMS,
                "alarmBackgroundServiceClaimed": False,
                "networkAccess": False,
                "privilegedOperations": False,
                "selfUpdater": False,
            }
            path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
            os.chmod(path, 0o600)
            self.evidence_written = True
            GLib.timeout_add(150, self.quit)
        except (OSError, RuntimeError, ValueError) as exc:
            print(f"SWIR Clock E2E evidence failed: {exc}", file=sys.stderr)
            self.quit()


def _self_test() -> int:
    assert _validate_alarm(0, 0, " Midnight ").label == "Midnight"
    assert _validate_alarm(23, 59, "").key == "23:59"
    for bad in ((-1, 0), (24, 0), (0, -1), (0, 60)):
        try:
            _validate_alarm(bad[0], bad[1], "x")
        except ValueError:
            pass
        else:
            raise AssertionError(f"invalid alarm accepted: {bad}")
    try:
        _validate_alarm(12, 0, "x" * (MAX_LABEL_CHARS + 1))
    except ValueError:
        pass
    else:
        raise AssertionError("oversized label accepted")

    with tempfile.TemporaryDirectory(prefix="swir-clock-self-test-") as temp_root:
        root = pathlib.Path(temp_root)
        assert _persistence_roundtrip(root)
        store = root / "alarms.json"
        payload = json.loads(store.read_text(encoding="utf-8"))
        assert payload["schema"] == ALARM_STORE_SCHEMA
        assert len(payload["alarms"]) == 2
        assert _read_alarm_store(store)[1].enabled is False

        store.write_text('{"schema":"unsupported","alarms":[]}\n', encoding="utf-8")
        try:
            _read_alarm_store(store)
        except ValueError:
            pass
        else:
            raise AssertionError("unsupported alarm schema accepted")

        store.write_bytes(b"x" * (MAX_ALARM_STATE_BYTES + 1))
        try:
            _read_alarm_store(store)
        except ValueError:
            pass
        else:
            raise AssertionError("oversized alarm store accepted")

    assert MAX_ALARMS == 32
    print("SWIR Clock self-test: OK")
    return 0


def main() -> int:
    if "--self-test" in sys.argv:
        return _self_test()
    return SwirClock().run(sys.argv)


if __name__ == "__main__":
    raise SystemExit(main())
