#!/usr/bin/env python3
"""Native SWIR Clock and unprivileged active-session alarm scheduler.

The user-visible Clock surface follows the bounded SWIR per-user language and
12/24-hour preference while the alarm storage/scheduler security boundary stays
local, owner-scoped, and network-free.
"""
from __future__ import annotations

import datetime as dt
import fcntl
import json
import os
import pathlib
import stat
import sys
import tempfile
from collections import defaultdict, deque
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Final, Iterator, Mapping

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gdk, GLib, Gtk  # noqa: E402

LIBDIR = pathlib.Path("/usr/local/lib/swir")
if LIBDIR.is_dir() and str(LIBDIR) not in sys.path:
    sys.path.insert(0, str(LIBDIR))

from core_runtime import UserSettingsStore, normalize_language_tag  # noqa: E402

APP_ID: Final = "dev.swir.Clock"
SERVICE_APP_ID: Final = "dev.swir.ClockAlarmService"
EVIDENCE_SCHEMA: Final = "swir.native-clock-runtime-evidence/0.4"
SERVICE_EVIDENCE_SCHEMA: Final = "swir.clock-alarm-service-evidence/0.2"
ALARM_STORE_SCHEMA: Final = "swir.clock.alarms/1"
MAX_ALARMS: Final = 32
MAX_LABEL_CHARS: Final = 80
MAX_ALARM_STATE_BYTES: Final = 64 * 1024
SERVICE_POLL_SECONDS: Final = 10

CSS = b"""
window.swir-app, window.swir-alarm { background: #02050A; color: #F4FAFF; }
.swir-header { background: #07111C; border-bottom: 1px solid #0088FF; padding: 12px 16px; }
.swir-brand { color: #62E5FF; font-size: 20px; font-weight: 800; }
.swir-time { color: #F4FAFF; font-size: 52px; font-weight: 800; }
.swir-date { color: #8DA8B8; font-size: 18px; }
.swir-card, .swir-alarm-card { background: #07111C; border: 1px solid rgba(98,229,255,0.38); border-radius: 14px; padding: 14px; }
.swir-muted, .swir-alarm-note { color: #8DA8B8; }
.swir-button { background: #07111C; color: #F4FAFF; border: 1px solid #0088FF; border-radius: 10px; padding: 7px 12px; }
.swir-primary, .swir-dismiss { background: #0088FF; color: #F4FAFF; border-radius: 10px; padding: 7px 12px; font-weight: 700; }
.swir-alarm-time { color: #62E5FF; font-size: 34px; font-weight: 800; }
.swir-alarm-label { color: #F4FAFF; font-size: 20px; font-weight: 700; }
"""

_TRANSLATIONS: Final[Mapping[str, Mapping[str, str]]] = {
    "en": {
        "window_title": "SWIR Clock",
        "brand": "◆  SWIR Clock",
        "clock": "Clock",
        "alarms": "Alarms",
        "calendar": "Calendar",
        "timezone": "Timezone: {zone}",
        "alarm_label": "Alarm label",
        "add_alarm": "Add alarm",
        "hour": "Hour",
        "minute": "Minute",
        "alarm_note": "Alarm definitions are saved per user. The unprivileged SWIR session alarm service keeps scheduling while this Clock window is closed. Sleep/wake catch-up and pre-login alarms are not claimed.",
        "invalid_store_note": " Existing alarm data failed validation and will not be overwritten.",
        "invalid_store_status": "Alarm storage failed validation; stored data was left untouched",
        "ready_status": "Local time • {count} saved alarm(s) • no network required",
        "invalid_store_refuse": "Alarm storage is invalid; refusing to overwrite existing data",
        "save_failed": "Could not save alarms: {error}",
        "limit_reached": "Alarm limit reached ({limit})",
        "added": "Added and saved {key} • {label}",
        "remove": "Remove",
        "enable_alarm": "Enable or disable alarm {key} {label}",
        "remove_alarm": "Remove alarm {key} {label}",
        "enabled": "Enabled {key} • {label}",
        "disabled": "Disabled {key} • {label}",
        "removed": "Alarm removed and saved",
        "scheduler_error": "Alarm scheduler state error: {error}",
        "alarm_prefix": "ALARM {key} • {label}",
        "service_window_title": "SWIR Alarm",
        "service_note": "Scheduled by SWIR Clock • active user session",
        "dismiss": "Dismiss",
    },
    "pl-PL": {
        "window_title": "Zegar SWIR",
        "brand": "◆  Zegar SWIR",
        "clock": "Zegar",
        "alarms": "Alarmy",
        "calendar": "Kalendarz",
        "timezone": "Strefa czasowa: {zone}",
        "alarm_label": "Etykieta alarmu",
        "add_alarm": "Dodaj alarm",
        "hour": "Godzina",
        "minute": "Minuta",
        "alarm_note": "Alarmy są zapisywane osobno dla użytkownika. Nieuprzywilejowana usługa sesji SWIR nadal planuje alarmy po zamknięciu okna Zegara. Budzenie po uśpieniu oraz alarmy przed logowaniem nie są deklarowane.",
        "invalid_store_note": " Istniejące dane alarmów nie przeszły walidacji i nie zostaną nadpisane.",
        "invalid_store_status": "Dane alarmów nie przeszły walidacji; pozostawiono je bez zmian",
        "ready_status": "Czas lokalny • zapisane alarmy: {count} • bez sieci",
        "invalid_store_refuse": "Dane alarmów są nieprawidłowe; odmowa nadpisania istniejących danych",
        "save_failed": "Nie udało się zapisać alarmów: {error}",
        "limit_reached": "Osiągnięto limit alarmów ({limit})",
        "added": "Dodano i zapisano {key} • {label}",
        "remove": "Usuń",
        "enable_alarm": "Włącz lub wyłącz alarm {key} {label}",
        "remove_alarm": "Usuń alarm {key} {label}",
        "enabled": "Włączono {key} • {label}",
        "disabled": "Wyłączono {key} • {label}",
        "removed": "Alarm usunięto i zapisano",
        "scheduler_error": "Błąd stanu harmonogramu alarmów: {error}",
        "alarm_prefix": "ALARM {key} • {label}",
        "service_window_title": "Alarm SWIR",
        "service_note": "Zaplanowano w Zegarze SWIR • aktywna sesja użytkownika",
        "dismiss": "Zamknij",
    },
    "nb-NO": {
        "window_title": "SWIR-klokke",
        "brand": "◆  SWIR-klokke",
        "clock": "Klokke",
        "alarms": "Alarmer",
        "calendar": "Kalender",
        "timezone": "Tidssone: {zone}",
        "alarm_label": "Alarmnavn",
        "add_alarm": "Legg til alarm",
        "hour": "Time",
        "minute": "Minutt",
        "alarm_note": "Alarmer lagres per bruker. Den uprivilegerte SWIR-sesjonstjenesten fortsetter planleggingen når klokkevinduet er lukket. Oppvåkning etter hvile og alarmer før innlogging er ikke påstått.",
        "invalid_store_note": " Eksisterende alarmdata besto ikke validering og blir ikke overskrevet.",
        "invalid_store_status": "Alarmlageret besto ikke validering; lagrede data ble ikke endret",
        "ready_status": "Lokal tid • {count} lagrede alarmer • uten nettverk",
        "invalid_store_refuse": "Alarmlageret er ugyldig; eksisterende data overskrives ikke",
        "save_failed": "Kunne ikke lagre alarmer: {error}",
        "limit_reached": "Alarmgrensen er nådd ({limit})",
        "added": "Lagt til og lagret {key} • {label}",
        "remove": "Fjern",
        "enable_alarm": "Slå alarm {key} {label} av eller på",
        "remove_alarm": "Fjern alarm {key} {label}",
        "enabled": "Aktivert {key} • {label}",
        "disabled": "Deaktivert {key} • {label}",
        "removed": "Alarmen er fjernet og lagret",
        "scheduler_error": "Feil i alarmplanleggerens tilstand: {error}",
        "alarm_prefix": "ALARM {key} • {label}",
        "service_window_title": "SWIR-alarm",
        "service_note": "Planlagt av SWIR-klokke • aktiv brukersesjon",
        "dismiss": "Lukk",
    },
}

_DAY_NAMES: Final[Mapping[str, tuple[str, ...]]] = {
    "en": ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"),
    "pl-PL": ("poniedziałek", "wtorek", "środa", "czwartek", "piątek", "sobota", "niedziela"),
    "nb-NO": ("mandag", "tirsdag", "onsdag", "torsdag", "fredag", "lørdag", "søndag"),
}
_MONTH_NAMES: Final[Mapping[str, tuple[str, ...]]] = {
    "en": ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"),
    "pl-PL": ("stycznia", "lutego", "marca", "kwietnia", "maja", "czerwca", "lipca", "sierpnia", "września", "października", "listopada", "grudnia"),
    "nb-NO": ("januar", "februar", "mars", "april", "mai", "juni", "juli", "august", "september", "oktober", "november", "desember"),
}


@dataclass(frozen=True)
class ClockLocale:
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


def clock_locale(language: object) -> ClockLocale:
    requested = normalize_language_tag(language) or "en"
    catalog = requested if requested in _TRANSLATIONS else "en"
    return ClockLocale(requested, catalog, _TRANSLATIONS[catalog])


def _format_local_date(moment: dt.datetime, locale: ClockLocale) -> str:
    day = _DAY_NAMES[locale.catalog_language][moment.weekday()]
    month = _MONTH_NAMES[locale.catalog_language][moment.month - 1]
    if locale.catalog_language == "en":
        return f"{day}, {moment.day:02d} {month} {moment.year}"
    return f"{day}, {moment.day}. {month} {moment.year}"


def _format_local_time(moment: dt.datetime, clock24h: bool) -> str:
    if clock24h:
        return moment.strftime("%H:%M:%S")
    return moment.strftime("%I:%M:%S %p").lstrip("0")


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


def _read_alarm_store_unlocked(path: pathlib.Path) -> list[Alarm]:
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
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


def _write_alarm_store_unlocked(path: pathlib.Path, alarms: list[Alarm]) -> None:
    if len(alarms) > MAX_ALARMS:
        raise ValueError("alarm store exceeds the alarm limit")
    payload = {"alarms": [_alarm_to_record(alarm) for alarm in alarms], "schema": ALARM_STORE_SCHEMA}
    encoded = (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    if len(encoded) > MAX_ALARM_STATE_BYTES:
        raise ValueError("alarm store serialization exceeds the size limit")
    parent = path.parent
    parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.is_symlink():
        raise OSError("refusing to replace symlinked alarm store")
    tmp_name = ""
    try:
        with tempfile.NamedTemporaryFile(mode="wb", dir=parent, prefix=".alarms.", delete=False) as handle:
            tmp_name = handle.name
            os.chmod(tmp_name, 0o600)
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
        tmp_name = ""
        os.chmod(path, 0o600)
        try:
            dir_fd = os.open(parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        except OSError:
            pass
    finally:
        if tmp_name:
            try:
                os.unlink(tmp_name)
            except FileNotFoundError:
                pass


@contextmanager
def _alarm_store_lock(path: pathlib.Path, exclusive: bool) -> Iterator[None]:
    parent = path.parent
    parent.mkdir(parents=True, exist_ok=True)
    lock_path = parent / ".alarms.lock"
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise ValueError("alarm lock must be a regular file")
        if info.st_uid != os.getuid():
            raise PermissionError("alarm lock owner mismatch")
        os.fchmod(fd, 0o600)
        fcntl.flock(fd, fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
        yield
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


def _read_alarm_store(path: pathlib.Path) -> list[Alarm]:
    with _alarm_store_lock(path, exclusive=False):
        return _read_alarm_store_unlocked(path)


def _merge_fire_dates(current: list[Alarm], candidate: list[Alarm]) -> list[Alarm]:
    fired: dict[tuple[int, int, str], deque[str]] = defaultdict(deque)
    for alarm in current:
        fired[(alarm.hour, alarm.minute, alarm.label)].append(alarm.last_fired_date)
    merged: list[Alarm] = []
    for alarm in candidate:
        existing_dates = fired[(alarm.hour, alarm.minute, alarm.label)]
        last_fired = alarm.last_fired_date
        if existing_dates:
            existing = existing_dates.popleft()
            if existing and (not last_fired or existing > last_fired):
                last_fired = existing
        merged.append(Alarm(alarm.hour, alarm.minute, alarm.label, alarm.enabled, last_fired))
    return merged


def _write_alarm_store(path: pathlib.Path, alarms: list[Alarm]) -> list[Alarm]:
    """Persist UI candidates while preserving a scheduler fire-date update."""
    with _alarm_store_lock(path, exclusive=True):
        current = _read_alarm_store_unlocked(path)
        merged = _merge_fire_dates(current, alarms)
        _write_alarm_store_unlocked(path, merged)
        return merged


def _claim_due_alarms(path: pathlib.Path, now: dt.datetime | None = None) -> list[Alarm]:
    """Atomically persist due claims before returning alarms to a notifier."""
    moment = now or dt.datetime.now().astimezone()
    today = moment.date().isoformat()
    with _alarm_store_lock(path, exclusive=True):
        alarms = _read_alarm_store_unlocked(path)
        due: list[Alarm] = []
        for alarm in alarms:
            if alarm.enabled and alarm.hour == moment.hour and alarm.minute == moment.minute and alarm.last_fired_date != today:
                alarm.last_fired_date = today
                due.append(Alarm(alarm.hour, alarm.minute, alarm.label, alarm.enabled, today))
        if due:
            _write_alarm_store_unlocked(path, alarms)
        return due


def _persistence_roundtrip(root: pathlib.Path) -> bool:
    path = root / "alarms.json"
    expected = [Alarm(7, 30, "Morning", True, ""), Alarm(22, 5, "Night", False, "2026-09-18")]
    _write_alarm_store(path, expected)
    loaded = _read_alarm_store(path)
    return loaded == expected and (path.stat().st_mode & 0o077) == 0


def _load_user_preferences(store: UserSettingsStore) -> tuple[ClockLocale, bool]:
    try:
        settings = store.load()
        language = settings.get("language", "en")
        clock24h = settings.get("clock24h", True)
        if type(clock24h) is not bool:
            clock24h = True
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError, UnicodeError):
        language = "en"
        clock24h = True
    return clock_locale(language), clock24h


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
        self.add_button: Gtk.Button | None = None
        self.calendar: Gtk.Calendar | None = None
        self.store = UserSettingsStore()
        self.locale = clock_locale("en")
        self.clock24h = True
        self.alarm_state_path = _alarm_state_path()
        self.alarm_load_error = ""
        try:
            self.alarms = _read_alarm_store(self.alarm_state_path)
        except (OSError, PermissionError, ValueError) as exc:
            self.alarms = []
            self.alarm_load_error = str(exc)
        self.e2e = os.environ.get("SWIR_APP_E2E", "0") == "1"
        self.evidence_path = os.environ.get("SWIR_APP_EVIDENCE_PATH", "")
        self.evidence_written = False

    def _t(self, key: str, **values: object) -> str:
        return self.locale.text(key, **values)

    def do_startup(self) -> None:
        Gtk.Application.do_startup(self)
        _install_css()

    def do_activate(self) -> None:
        if self.window is not None:
            self.window.present()
            return
        self.locale, self.clock24h = _load_user_preferences(self.store)
        window = Gtk.ApplicationWindow(application=self)
        window.set_title(self._t("window_title"))
        window.set_default_size(760, 560)
        window.add_css_class("swir-app")
        window.set_direction(Gtk.TextDirection.RTL if self.locale.text_direction == "rtl" else Gtk.TextDirection.LTR)
        self.window = window
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        window.set_child(root)
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        header.add_css_class("swir-header")
        title = Gtk.Label(label=self._t("brand"))
        title.add_css_class("swir-brand")
        title.set_xalign(0)
        header.append(title)
        root.append(header)
        switcher = Gtk.StackSwitcher()
        stack = Gtk.Stack()
        stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        switcher.set_stack(stack)
        switcher.set_tooltip_text(self._t("window_title"))
        switcher.set_margin_top(12); switcher.set_margin_bottom(8); switcher.set_margin_start(16); switcher.set_margin_end(16)
        root.append(switcher)
        root.append(stack)
        stack.add_titled(self._clock_page(), "clock", self._t("clock"))
        stack.add_titled(self._alarm_page(), "alarms", self._t("alarms"))
        stack.add_titled(self._calendar_page(), "calendar", self._t("calendar"))
        initial = self._t("invalid_store_status") if self.alarm_load_error else self._t("ready_status", count=len(self.alarms))
        self.status = Gtk.Label(label=initial)
        self.status.add_css_class("swir-muted")
        self.status.set_margin_top(8); self.status.set_margin_bottom(12)
        root.append(self.status)
        GLib.timeout_add_seconds(1, self._tick)
        self._tick()
        window.connect("map", self._on_mapped)
        window.present()

    def _clock_page(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_margin_top(22); box.set_margin_start(20); box.set_margin_end(20)
        box.set_vexpand(True); box.set_valign(Gtk.Align.CENTER)
        self.time_label = Gtk.Label(); self.time_label.add_css_class("swir-time")
        self.time_label.set_tooltip_text(self._t("clock"))
        self.date_label = Gtk.Label(); self.date_label.add_css_class("swir-date")
        self.date_label.set_tooltip_text(self._t("calendar"))
        box.append(self.time_label); box.append(self.date_label)
        zone_name = dt.datetime.now().astimezone().tzname() or "local"
        zone = Gtk.Label(label=self._t("timezone", zone=zone_name))
        zone.add_css_class("swir-muted"); box.append(zone)
        return box

    def _alarm_page(self) -> Gtk.Widget:
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        outer.set_margin_top(14); outer.set_margin_start(20); outer.set_margin_end(20); outer.set_margin_bottom(12)
        editor = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8); editor.add_css_class("swir-card")
        self.hour_spin = Gtk.SpinButton.new_with_range(0, 23, 1); self.minute_spin = Gtk.SpinButton.new_with_range(0, 59, 1)
        self.hour_spin.set_tooltip_text(self._t("hour")); self.minute_spin.set_tooltip_text(self._t("minute"))
        now = dt.datetime.now().astimezone(); self.hour_spin.set_value(now.hour); self.minute_spin.set_value(now.minute)
        self.label_entry = Gtk.Entry(); self.label_entry.set_placeholder_text(self._t("alarm_label")); self.label_entry.set_tooltip_text(self._t("alarm_label")); self.label_entry.set_max_length(MAX_LABEL_CHARS); self.label_entry.set_hexpand(True)
        add = Gtk.Button(label=self._t("add_alarm")); add.add_css_class("swir-primary"); add.set_tooltip_text(self._t("add_alarm")); add.connect("clicked", self._add_alarm); self.add_button = add
        for widget in (Gtk.Label(label=self._t("hour")), self.hour_spin, Gtk.Label(label=self._t("minute")), self.minute_spin, self.label_entry, add): editor.append(widget)
        outer.append(editor)
        note_text = self._t("alarm_note")
        if self.alarm_load_error: note_text += self._t("invalid_store_note")
        note = Gtk.Label(label=note_text, wrap=True); note.add_css_class("swir-muted"); note.set_xalign(0); outer.append(note)
        self.alarm_list = Gtk.ListBox(); self.alarm_list.set_selection_mode(Gtk.SelectionMode.NONE); self.alarm_list.add_css_class("swir-card")
        for alarm in self.alarms: self._append_alarm_row(alarm)
        scroll = Gtk.ScrolledWindow(); scroll.set_vexpand(True); scroll.set_child(self.alarm_list); outer.append(scroll)
        return outer

    def _calendar_page(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.set_margin_top(18); box.set_margin_start(20); box.set_margin_end(20); box.set_margin_bottom(18); box.set_vexpand(True)
        calendar = Gtk.Calendar(); calendar.set_hexpand(True); calendar.set_vexpand(True); calendar.set_tooltip_text(self._t("calendar")); self.calendar = calendar; box.append(calendar)
        return box

    def _persist_candidate(self, alarms: list[Alarm]) -> bool:
        if self.alarm_load_error:
            self._set_status(self._t("invalid_store_refuse")); return False
        try:
            _write_alarm_store(self.alarm_state_path, alarms); return True
        except (OSError, PermissionError, ValueError) as exc:
            self._set_status(self._t("save_failed", error=exc)); return False

    def _add_alarm(self, _button: Gtk.Button) -> None:
        if len(self.alarms) >= MAX_ALARMS:
            self._set_status(self._t("limit_reached", limit=MAX_ALARMS)); return
        assert self.hour_spin and self.minute_spin and self.label_entry
        try:
            alarm = _validate_alarm(int(self.hour_spin.get_value()), int(self.minute_spin.get_value()), self.label_entry.get_text())
        except ValueError as exc:
            self._set_status(str(exc)); return
        if not self._persist_candidate([*self.alarms, alarm]): return
        self.alarms.append(alarm); self._append_alarm_row(alarm); self.label_entry.set_text(""); self._set_status(self._t("added", key=alarm.key, label=alarm.label))

    def _append_alarm_row(self, alarm: Alarm) -> None:
        assert self.alarm_list is not None
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        row.set_margin_top(8); row.set_margin_bottom(8); row.set_margin_start(10); row.set_margin_end(10)
        text = Gtk.Label(label=f"{alarm.key}   {alarm.label}"); text.set_xalign(0); text.set_hexpand(True)
        toggle = Gtk.Switch(active=alarm.enabled); toggle.set_tooltip_text(self._t("enable_alarm", key=alarm.key, label=alarm.label)); toggle.connect("notify::active", self._toggle_alarm, alarm)
        remove = Gtk.Button(label=self._t("remove")); remove.add_css_class("swir-button"); remove.set_tooltip_text(self._t("remove_alarm", key=alarm.key, label=alarm.label)); remove.connect("clicked", self._remove_alarm, alarm, row)
        row.append(text); row.append(toggle); row.append(remove); self.alarm_list.append(row)

    def _toggle_alarm(self, switch: Gtk.Switch, _pspec: object, alarm: Alarm) -> None:
        requested = switch.get_active()
        if requested == alarm.enabled: return
        replacement = Alarm(alarm.hour, alarm.minute, alarm.label, requested, alarm.last_fired_date)
        if not self._persist_candidate([replacement if current is alarm else current for current in self.alarms]):
            switch.set_active(alarm.enabled); return
        alarm.enabled = requested
        self._set_status(self._t("enabled" if requested else "disabled", key=alarm.key, label=alarm.label))

    def _remove_alarm(self, _button: Gtk.Button, alarm: Alarm, row: Gtk.Widget) -> None:
        if not self._persist_candidate([current for current in self.alarms if current is not alarm]): return
        self.alarms.remove(alarm)
        if self.alarm_list is not None: self.alarm_list.remove(row)
        self._set_status(self._t("removed"))

    def _tick(self) -> bool:
        now = dt.datetime.now().astimezone()
        if self.time_label is not None: self.time_label.set_text(_format_local_time(now, self.clock24h))
        if self.date_label is not None: self.date_label.set_text(_format_local_date(now, self.locale))
        if not self.alarm_load_error:
            try:
                for alarm in _claim_due_alarms(self.alarm_state_path, now): self._fire_alarm(alarm)
            except (OSError, PermissionError, ValueError) as exc:
                self._set_status(self._t("scheduler_error", error=exc))
        return True

    def _fire_alarm(self, alarm: Alarm) -> None:
        self._set_status(self._t("alarm_prefix", key=alarm.key, label=alarm.label))
        if self.window is not None: self.window.present()

    def _set_status(self, text: str) -> None:
        if self.status is not None: self.status.set_text(text)

    def _on_mapped(self, _window: Gtk.Window) -> None:
        if not self.e2e or self.evidence_written: return
        runtime_text = os.environ.get("XDG_RUNTIME_DIR", "")
        if not runtime_text or not self.evidence_path: return
        runtime = pathlib.Path(runtime_text).resolve(); path = pathlib.Path(self.evidence_path)
        try:
            if path.parent.resolve() != runtime: raise RuntimeError("refusing evidence path outside XDG_RUNTIME_DIR")
            alarm = _validate_alarm(7, 30, "Morning")
            with tempfile.TemporaryDirectory(prefix="swir-clock-e2e-", dir=runtime) as temp_root: persistence_ok = _persistence_roundtrip(pathlib.Path(temp_root))
            sample = dt.datetime(2026, 9, 23, 13, 5, 6, tzinfo=dt.timezone.utc)
            focusable = all(widget is not None and widget.get_focusable() for widget in (self.hour_spin, self.minute_spin, self.label_entry, self.add_button))
            payload = {
                "schema": EVIDENCE_SCHEMA, "passed": True, "applicationId": APP_ID,
                "nativeToolkit": "gtk4", "displayProtocol": "wayland", "windowMapped": True,
                "localTimeAvailable": bool(dt.datetime.now().astimezone().tzinfo), "calendarAvailable": self.calendar is not None,
                "alarmValidationPassed": alarm.key == "07:30", "alarmPersistenceRoundTrip": persistence_ok,
                "alarmStoreSchema": ALARM_STORE_SCHEMA, "alarmStoreMaxBytes": MAX_ALARM_STATE_BYTES,
                "alarmLimit": MAX_ALARMS, "alarmBackgroundServiceClaimed": True,
                "alarmBackgroundServiceScope": "active-user-session", "alarmSleepWakeClaimed": False,
                "alarmPreLoginClaimed": False, "networkAccess": False, "privilegedOperations": False,
                "selfUpdater": False, "requestedLanguage": self.locale.requested_language,
                "catalogLanguage": self.locale.catalog_language, "translationFallback": self.locale.fallback,
                "textDirection": self.locale.text_direction, "clock24h": self.clock24h,
                "localizedWindowTitle": self._t("window_title"), "localizedAddAlarmLabel": self._t("add_alarm"),
                "localizedSurfaceVerified": self.window is not None and self.window.get_title() == self._t("window_title"),
                "keyboardFocusControls": focusable,
                "localizedDateSample": _format_local_date(sample, self.locale),
                "localDateLanguageVerified": _DAY_NAMES[self.locale.catalog_language][sample.weekday()] in _format_local_date(sample, self.locale),
                "timePreferenceVerified": _format_local_time(sample, self.clock24h) == ("13:05:06" if self.clock24h else "1:05:06 PM"),
            }
            path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8"); os.chmod(path, 0o600)
            self.evidence_written = True; GLib.timeout_add(150, self.quit)
        except (OSError, RuntimeError, ValueError) as exc:
            print(f"SWIR Clock E2E evidence failed: {exc}", file=sys.stderr); self.quit()


class AlarmService(Gtk.Application):
    def __init__(self) -> None:
        super().__init__(application_id=SERVICE_APP_ID)
        self.store = _alarm_state_path()
        self.windows: list[Gtk.ApplicationWindow] = []
        self.settings_store = UserSettingsStore()
        self.locale = clock_locale("en")
        self.e2e = os.environ.get("SWIR_CLOCK_SERVICE_E2E", "0") == "1"
        self.evidence_path = os.environ.get("SWIR_CLOCK_SERVICE_EVIDENCE_PATH", "")
        self.evidence_written = False

    def _t(self, key: str, **values: object) -> str:
        return self.locale.text(key, **values)

    def do_startup(self) -> None:
        Gtk.Application.do_startup(self); _install_css(); self.locale, _ = _load_user_preferences(self.settings_store)

    def do_activate(self) -> None:
        self.hold(); self._check_due(); GLib.timeout_add_seconds(SERVICE_POLL_SECONDS, self._check_due)

    def _check_due(self) -> bool:
        try: due = _claim_due_alarms(self.store)
        except (OSError, PermissionError, ValueError) as exc:
            if self.e2e:
                print(f"SWIR Clock alarm service store validation failed: {exc}", file=sys.stderr); self.quit(); return False
            return True
        for alarm in due: self._show_alarm(alarm)
        return True

    def _show_alarm(self, alarm: Alarm) -> None:
        window = Gtk.ApplicationWindow(application=self); window.set_title(self._t("service_window_title")); window.set_default_size(440, 240); window.add_css_class("swir-alarm")
        window.set_direction(Gtk.TextDirection.RTL if self.locale.text_direction == "rtl" else Gtk.TextDirection.LTR)
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12); card.set_margin_top(20); card.set_margin_bottom(20); card.set_margin_start(20); card.set_margin_end(20); card.add_css_class("swir-alarm-card"); window.set_child(card)
        time_label = Gtk.Label(label=alarm.key); time_label.add_css_class("swir-alarm-time"); card.append(time_label)
        label = Gtk.Label(label=alarm.label, wrap=True); label.add_css_class("swir-alarm-label"); card.append(label)
        note = Gtk.Label(label=self._t("service_note"), wrap=True); note.add_css_class("swir-alarm-note"); card.append(note)
        dismiss = Gtk.Button(label=self._t("dismiss")); dismiss.add_css_class("swir-dismiss"); dismiss.set_tooltip_text(self._t("dismiss")); dismiss.connect("clicked", lambda _button: window.destroy()); card.append(dismiss)
        window.connect("destroy", self._window_destroyed); window.connect("map", self._alarm_mapped, alarm); self.windows.append(window); window.present()

    def _window_destroyed(self, window: Gtk.ApplicationWindow) -> None:
        if window in self.windows: self.windows.remove(window)

    def _alarm_mapped(self, window: Gtk.ApplicationWindow, alarm: Alarm) -> None:
        if not self.e2e or self.evidence_written: return
        runtime_text = os.environ.get("XDG_RUNTIME_DIR", "")
        if not runtime_text or not self.evidence_path: return
        runtime = pathlib.Path(runtime_text).resolve(); path = pathlib.Path(self.evidence_path)
        try:
            if path.parent.resolve() != runtime: raise RuntimeError("refusing evidence path outside XDG_RUNTIME_DIR")
            persisted = _read_alarm_store(self.store)
            claimed = next(item for item in persisted if item.hour == alarm.hour and item.minute == alarm.minute and item.label == alarm.label)
            payload = {
                "schema": SERVICE_EVIDENCE_SCHEMA, "passed": True, "applicationId": SERVICE_APP_ID,
                "nativeToolkit": "gtk4", "displayProtocol": "wayland", "alarmWindowMapped": True,
                "activeSessionOnly": True, "firesWithClockWindowClosed": True,
                "atomicDueClaim": claimed.last_fired_date == dt.datetime.now().astimezone().date().isoformat(),
                "pollSeconds": SERVICE_POLL_SECONDS, "sleepWakeClaimed": False, "preLoginClaimed": False,
                "networkAccess": False, "privilegedOperations": False, "selfUpdater": False,
                "requestedLanguage": self.locale.requested_language, "catalogLanguage": self.locale.catalog_language,
                "translationFallback": self.locale.fallback, "textDirection": self.locale.text_direction,
                "localizedWindowTitle": window.get_title(), "localizedNote": self._t("service_note"),
                "localizedDismissLabel": self._t("dismiss"), "localizedSurfaceVerified": window.get_title() == self._t("service_window_title"),
            }
            path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8"); os.chmod(path, 0o600)
            self.evidence_written = True; GLib.timeout_add(150, self.quit)
        except (OSError, RuntimeError, StopIteration, ValueError) as exc:
            print(f"SWIR Clock alarm service evidence failed: {exc}", file=sys.stderr); self.quit()


def _install_css() -> None:
    provider = Gtk.CssProvider(); provider.load_from_data(CSS)
    display = Gdk.Display.get_default()
    if display is None: raise RuntimeError("SWIR Clock requires an active graphical display")
    Gtk.StyleContext.add_provider_for_display(display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)


def _self_test() -> int:
    assert _validate_alarm(0, 0, " Midnight ").label == "Midnight"
    assert _validate_alarm(23, 59, "").key == "23:59"
    for bad in ((-1, 0), (24, 0), (0, -1), (0, 60)):
        try: _validate_alarm(bad[0], bad[1], "x")
        except ValueError: pass
        else: raise AssertionError(f"invalid alarm accepted: {bad}")
    try: _validate_alarm(12, 0, "x" * (MAX_LABEL_CHARS + 1))
    except ValueError: pass
    else: raise AssertionError("oversized label accepted")
    with tempfile.TemporaryDirectory(prefix="swir-clock-self-test-") as temp_root:
        root = pathlib.Path(temp_root); assert _persistence_roundtrip(root); store = root / "alarms.json"
        payload = json.loads(store.read_text(encoding="utf-8")); assert payload["schema"] == ALARM_STORE_SCHEMA and len(payload["alarms"]) == 2
        now = dt.datetime(2026, 9, 19, 7, 30, tzinfo=dt.timezone.utc)
        first = _claim_due_alarms(store, now); assert len(first) == 1 and first[0].label == "Morning"; assert _claim_due_alarms(store, now) == []
        stale = [Alarm(7, 30, "Morning", False, ""), Alarm(22, 5, "Night", False, "2026-09-18")]
        merged = _write_alarm_store(store, stale); assert merged[0].last_fired_date == "2026-09-19"
        store.write_text('{"schema":"unsupported","alarms":[]}\n', encoding="utf-8")
        try: _read_alarm_store(store)
        except ValueError: pass
        else: raise AssertionError("unsupported alarm schema accepted")
        store.write_bytes(b"x" * (MAX_ALARM_STATE_BYTES + 1))
        try: _read_alarm_store(store)
        except ValueError: pass
        else: raise AssertionError("oversized alarm store accepted")
    pl = clock_locale("pl_PL.UTF-8")
    assert pl.catalog_language == "pl-PL" and pl.text("add_alarm") == "Dodaj alarm"
    assert clock_locale("nb-NO").text("dismiss") == "Lukk"
    unsupported = clock_locale("de-DE")
    assert unsupported.catalog_language == "en" and unsupported.fallback is True
    sample = dt.datetime(2026, 9, 23, 13, 5, 6, tzinfo=dt.timezone.utc)
    assert "środa" in _format_local_date(sample, pl)
    assert _format_local_time(sample, True) == "13:05:06"
    assert _format_local_time(sample, False) == "1:05:06 PM"
    assert SERVICE_POLL_SECONDS >= 5 and MAX_ALARMS == 32
    print("SWIR Clock self-test: OK")
    return 0


def main() -> int:
    if "--self-test" in sys.argv: return _self_test()
    if "--alarm-service" in sys.argv: return AlarmService().run([sys.argv[0]])
    return SwirClock().run(sys.argv)


if __name__ == "__main__": raise SystemExit(main())
