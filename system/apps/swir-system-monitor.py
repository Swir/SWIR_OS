#!/usr/bin/env python3
"""SWIR System Monitor — native GTK4 task manager, resource viewer and diagnostics surface."""

from __future__ import annotations

import json
import os
import pathlib
import signal
import subprocess
import sys
import tempfile
import threading
from dataclasses import dataclass
from typing import Callable, Final

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gdk, GLib, Gtk  # noqa: E402

APP_ID: Final = "dev.swir.SystemMonitor"
EVIDENCE_SCHEMA: Final = "swir.native-system-monitor-runtime-evidence/0.1"
MAX_PROCESS_ROWS: Final = 200
MAX_PROCESS_NAME_CHARS: Final = 120
MAX_FILTER_CHARS: Final = 80
COMMAND_TIMEOUT_SECONDS: Final = 3
MAX_COMMAND_OUTPUT_CHARS: Final = 64 * 1024
JOURNAL_LINE_LIMIT: Final = 50
SYSTEMCTL_PATH: Final = "/usr/bin/systemctl"
JOURNALCTL_PATH: Final = "/usr/bin/journalctl"
FAILED_UNITS_COMMAND: Final = (SYSTEMCTL_PATH, "--failed", "--no-legend", "--plain")
JOURNAL_WARNINGS_COMMAND: Final = (
    JOURNALCTL_PATH,
    "-b",
    "-p",
    "warning",
    "--no-pager",
    "-n",
    str(JOURNAL_LINE_LIMIT),
    "-o",
    "short-monotonic",
)
ALLOWED_DIAGNOSTIC_COMMANDS: Final = frozenset({FAILED_UNITS_COMMAND, JOURNAL_WARNINGS_COMMAND})
PROC_ROOT: Final = pathlib.Path("/proc")

CSS = b"""
window.swir-app { background: #02050A; color: #F4FAFF; }
.swir-header { background: #07111C; border-bottom: 1px solid #0088FF; padding: 10px 14px; }
.swir-brand { color: #62E5FF; font-size: 18px; font-weight: 800; }
.swir-muted { color: #8DA8B8; }
.swir-metric { background: #07111C; border: 1px solid rgba(98,229,255,0.28); border-radius: 12px; padding: 10px 14px; }
.swir-row { padding: 7px 10px; border-bottom: 1px solid rgba(98,229,255,0.08); }
.swir-diag { background: #07111C; border: 1px solid rgba(98,229,255,0.18); border-radius: 12px; padding: 12px; }
.swir-control { background: #07111C; color: #F4FAFF; border: 1px solid rgba(0,136,255,0.72); border-radius: 10px; padding: 7px 10px; }
.swir-danger { background: #2A0A0A; color: #FFD9D9; border: 1px solid #F06A6A; border-radius: 10px; padding: 7px 12px; }
"""

@dataclass(frozen=True)
class ProcessRow:
    pid: int
    name: str
    rss_kib: int
    uid: int
    start_ticks: int


@dataclass(frozen=True)
class ProcessIdentity:
    pid: int
    name: str
    uid: int
    start_ticks: int


@dataclass(frozen=True)
class CommandResult:
    status: str
    returncode: int | None
    stdout: str
    stderr: str


@dataclass(frozen=True)
class DiagnosticsSnapshot:
    os_name: str
    kernel_version: str
    uptime_seconds: float
    failed: CommandResult
    journal: CommandResult


class ProcessTerminationError(RuntimeError):
    """Raised when a process does not satisfy the safe same-user SIGTERM contract."""


def read_meminfo() -> dict[str, int]:
    values: dict[str, int] = {}
    with open("/proc/meminfo", encoding="utf-8") as handle:
        for line in handle:
            key, raw = line.split(":", 1)
            parts = raw.strip().split()
            if parts and parts[0].isdigit():
                values[key] = int(parts[0])
    return values


def read_uptime_seconds() -> float:
    with open("/proc/uptime", encoding="utf-8") as handle:
        return float(handle.read().split()[0])


def _parse_status(path: pathlib.Path) -> tuple[int, int, str]:
    uid = -1
    ppid = -1
    name = ""
    with path.open(encoding="utf-8") as handle:
        for raw in handle:
            if raw.startswith("Uid:"):
                parts = raw.split()
                if len(parts) >= 2 and parts[1].isdigit():
                    uid = int(parts[1])
            elif raw.startswith("PPid:"):
                parts = raw.split()
                if len(parts) >= 2 and parts[1].isdigit():
                    ppid = int(parts[1])
            elif raw.startswith("Name:"):
                name = raw.split(":", 1)[1].strip()
    if uid < 0:
        raise ProcessTerminationError("process UID is unavailable")
    return uid, ppid, name[:MAX_PROCESS_NAME_CHARS]


def _parse_start_ticks(stat_text: str) -> int:
    close = stat_text.rfind(")")
    if close <= 0:
        raise ProcessTerminationError("process stat record is malformed")
    tail = stat_text[close + 1 :].strip().split()
    # /proc/PID/stat field 22 (starttime); tail starts at field 3.
    if len(tail) <= 19 or not tail[19].isdigit():
        raise ProcessTerminationError("process start identity is unavailable")
    return int(tail[19])


def read_process_identity(pid: int, proc_root: pathlib.Path = PROC_ROOT) -> ProcessIdentity:
    if not isinstance(pid, int) or pid <= 0:
        raise ProcessTerminationError("invalid process id")
    entry = proc_root / str(pid)
    try:
        uid, _ppid, status_name = _parse_status(entry / "status")
        stat_text = (entry / "stat").read_text(encoding="utf-8")
        start_ticks = _parse_start_ticks(stat_text)
        comm_name = (entry / "comm").read_text(encoding="utf-8").strip()
    except ProcessTerminationError:
        raise
    except (FileNotFoundError, PermissionError, ProcessLookupError, OSError, UnicodeError) as exc:
        raise ProcessTerminationError("process is no longer available") from exc
    name = (comm_name or status_name or f"pid-{pid}")[:MAX_PROCESS_NAME_CHARS]
    return ProcessIdentity(pid=pid, name=name, uid=uid, start_ticks=start_ticks)


def read_processes(limit: int = MAX_PROCESS_ROWS, proc_root: pathlib.Path = PROC_ROOT) -> list[ProcessRow]:
    rows: list[ProcessRow] = []
    try:
        entries = list(proc_root.iterdir())
    except OSError:
        return rows
    for entry in entries:
        if not entry.name.isdigit():
            continue
        pid = int(entry.name)
        try:
            identity = read_process_identity(pid, proc_root)
            rss_kib = 0
            with (entry / "status").open(encoding="utf-8") as handle:
                for line in handle:
                    if line.startswith("VmRSS:"):
                        parts = line.split()
                        if len(parts) >= 2 and parts[1].isdigit():
                            rss_kib = int(parts[1])
                        break
        except (ProcessTerminationError, FileNotFoundError, PermissionError, ProcessLookupError, OSError, UnicodeError):
            continue
        rows.append(
            ProcessRow(
                pid=identity.pid,
                name=identity.name,
                rss_kib=rss_kib,
                uid=identity.uid,
                start_ticks=identity.start_ticks,
            )
        )
    rows.sort(key=lambda row: (-row.rss_kib, row.pid))
    return rows[: max(0, min(int(limit), MAX_PROCESS_ROWS))]


def _ancestor_pids(proc_root: pathlib.Path = PROC_ROOT, start_pid: int | None = None) -> set[int]:
    current = os.getpid() if start_pid is None else int(start_pid)
    protected: set[int] = set()
    for _ in range(64):
        if current <= 0 or current in protected:
            break
        protected.add(current)
        if current == 1:
            break
        try:
            _uid, ppid, _name = _parse_status(proc_root / str(current) / "status")
        except (ProcessTerminationError, OSError, UnicodeError):
            break
        if ppid <= 0 or ppid == current:
            break
        current = ppid
    protected.update({1, os.getpid(), os.getppid()})
    return protected


def _send_sigterm_pidfd(pid: int) -> None:
    """Send SIGTERM to one PID, preferring a pidfd to avoid PID-reuse races."""
    if hasattr(os, "pidfd_open") and hasattr(signal, "pidfd_send_signal"):
        fd = os.pidfd_open(pid, 0)
        try:
            signal.pidfd_send_signal(fd, signal.SIGTERM, None, 0)
        finally:
            os.close(fd)
        return
    os.kill(pid, signal.SIGTERM)


def terminate_same_user_process(
    target: ProcessRow | ProcessIdentity,
    *,
    proc_root: pathlib.Path = PROC_ROOT,
    current_uid: int | None = None,
    protected_pids: set[int] | None = None,
    sender: Callable[[int], None] | None = None,
) -> None:
    """Revalidate process identity and send only SIGTERM to a same-user process."""
    uid = os.getuid() if current_uid is None else int(current_uid)
    protected = _ancestor_pids(proc_root) if protected_pids is None else set(protected_pids)
    if target.pid <= 1 or target.pid in protected:
        raise ProcessTerminationError("SWIR protects the current session and its ancestor processes")
    if target.uid != uid:
        raise ProcessTerminationError("only processes owned by the signed-in user can be ended")

    live = read_process_identity(target.pid, proc_root)
    if live.uid != uid:
        raise ProcessTerminationError("process ownership changed before termination")
    if live.start_ticks != target.start_ticks:
        raise ProcessTerminationError("process identity changed; refusing a reused PID")
    if live.name != target.name:
        raise ProcessTerminationError("process identity changed; refresh before ending it")

    send = _send_sigterm_pidfd if sender is None else sender
    try:
        send(target.pid)
    except (PermissionError, ProcessLookupError, OSError) as exc:
        raise ProcessTerminationError(f"could not send SIGTERM: {exc}") from exc


def format_mib(kib: int) -> str:
    return f"{kib / 1024.0:.1f} MiB"


def read_os_release() -> str:
    values: dict[str, str] = {}
    try:
        with open("/etc/os-release", encoding="utf-8") as handle:
            for raw_line in handle:
                line = raw_line.strip()
                if not line or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                values[key] = value.strip().strip('"')
    except (OSError, UnicodeError):
        return "Unknown Linux"
    return values.get("PRETTY_NAME") or values.get("NAME") or "Unknown Linux"


def read_kernel_version() -> str:
    try:
        value = pathlib.Path("/proc/version").read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        return "Unavailable"
    return value[:512] or "Unavailable"


def _diagnostic_env() -> dict[str, str]:
    env = {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}
    for key in ("DBUS_SESSION_BUS_ADDRESS", "XDG_RUNTIME_DIR"):
        value = os.environ.get(key)
        if value:
            env[key] = value
    return env


def run_read_only_command(argv: tuple[str, ...]) -> CommandResult:
    if argv not in ALLOWED_DIAGNOSTIC_COMMANDS:
        raise ValueError("diagnostic command is not allow-listed")
    if not pathlib.Path(argv[0]).is_file():
        return CommandResult("unavailable", None, "", "")
    try:
        completed = subprocess.run(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=COMMAND_TIMEOUT_SECONDS,
            check=False,
            shell=False,
            env=_diagnostic_env(),
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
        if isinstance(stdout, bytes):
            stdout = stdout.decode("utf-8", errors="replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", errors="replace")
        return CommandResult(
            "timeout", None, stdout[:MAX_COMMAND_OUTPUT_CHARS], stderr[:MAX_COMMAND_OUTPUT_CHARS]
        )
    except OSError:
        return CommandResult("unavailable", None, "", "")
    return CommandResult(
        "ok" if completed.returncode == 0 else "error",
        completed.returncode,
        completed.stdout[:MAX_COMMAND_OUTPUT_CHARS],
        completed.stderr[:MAX_COMMAND_OUTPUT_CHARS],
    )


def _nonempty_lines(text: str, limit: int) -> list[str]:
    return [line for line in text.splitlines() if line.strip()][:limit]


def _write_fake_process(root: pathlib.Path, pid: int, uid: int, start_ticks: int, name: str, ppid: int = 1) -> ProcessRow:
    entry = root / str(pid)
    entry.mkdir(parents=True)
    (entry / "status").write_text(
        f"Name:\t{name}\nUid:\t{uid}\t{uid}\t{uid}\t{uid}\nPPid:\t{ppid}\nVmRSS:\t1024 kB\n",
        encoding="utf-8",
    )
    # Fields 3..21 contain 19 values before field 22=starttime.
    tail = ["S"] + [str(ppid)] + ["0"] * 17 + [str(start_ticks)] + ["0"] * 4
    (entry / "stat").write_text(f"{pid} ({name}) " + " ".join(tail) + "\n", encoding="utf-8")
    (entry / "comm").write_text(name + "\n", encoding="utf-8")
    ident = read_process_identity(pid, root)
    return ProcessRow(pid=pid, name=ident.name, rss_kib=1024, uid=ident.uid, start_ticks=ident.start_ticks)


def _self_test() -> int:
    with tempfile.TemporaryDirectory(prefix="swir-task-manager-selftest-") as tmp:
        root = pathlib.Path(tmp)
        sent: list[int] = []

        safe = _write_fake_process(root, 4242, 1000, 777, "safe-test")
        terminate_same_user_process(
            safe,
            proc_root=root,
            current_uid=1000,
            protected_pids={1, 99},
            sender=sent.append,
        )
        assert sent == [4242]

        foreign = _write_fake_process(root, 4343, 1001, 888, "foreign-test")
        try:
            terminate_same_user_process(
                foreign,
                proc_root=root,
                current_uid=1000,
                protected_pids={1},
                sender=sent.append,
            )
        except ProcessTerminationError:
            pass
        else:
            raise AssertionError("foreign-user process termination was accepted")

        protected = _write_fake_process(root, 4444, 1000, 999, "protected-test")
        try:
            terminate_same_user_process(
                protected,
                proc_root=root,
                current_uid=1000,
                protected_pids={1, 4444},
                sender=sent.append,
            )
        except ProcessTerminationError:
            pass
        else:
            raise AssertionError("protected process termination was accepted")

        reused = _write_fake_process(root, 4545, 1000, 111, "reused-test")
        (root / "4545" / "stat").write_text(
            "4545 (reused-test) " + " ".join(["S", "1"] + ["0"] * 17 + ["222"] + ["0"] * 4) + "\n",
            encoding="utf-8",
        )
        try:
            terminate_same_user_process(
                reused,
                proc_root=root,
                current_uid=1000,
                protected_pids={1},
                sender=sent.append,
            )
        except ProcessTerminationError:
            pass
        else:
            raise AssertionError("PID-reuse identity mismatch was accepted")

        rows = read_processes(proc_root=root)
        assert rows and len(rows) <= MAX_PROCESS_ROWS
        assert MAX_FILTER_CHARS == 80

    print("SWIR System Monitor task-manager self-test: OK")
    return 0


class SwirSystemMonitor(Gtk.Application):
    def __init__(self) -> None:
        super().__init__(application_id=APP_ID)
        self.window: Gtk.ApplicationWindow | None = None
        self.metrics: Gtk.Label | None = None
        self.listbox: Gtk.ListBox | None = None
        self.process_filter: Gtk.SearchEntry | None = None
        self.end_process_button: Gtk.Button | None = None
        self.process_status: Gtk.Label | None = None
        self.diag_summary: Gtk.Label | None = None
        self.diag_text: Gtk.TextView | None = None
        self.diag_refresh: Gtk.Button | None = None
        self.e2e = os.environ.get("SWIR_APP_E2E", "0") == "1"
        self.evidence_path = os.environ.get("SWIR_APP_EVIDENCE_PATH", "")
        self.last_process_count = 0
        self.last_mem_total_kib = 0
        self.failed_units_status = "not-run"
        self.journal_status = "not-run"
        self.failed_units_count = 0
        self.journal_visible_line_count = 0
        self.diagnostics_running = False
        self.diagnostics_ready = False
        self.evidence_written = False

    def do_startup(self) -> None:
        Gtk.Application.do_startup(self)
        provider = Gtk.CssProvider()
        provider.load_from_data(CSS)
        display = Gdk.Display.get_default()
        if display is None:
            raise RuntimeError("SWIR System Monitor requires a graphical display")
        Gtk.StyleContext.add_provider_for_display(display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    def do_activate(self) -> None:
        if self.window is not None:
            self.window.present()
            return

        window = Gtk.ApplicationWindow(application=self)
        window.set_title("SWIR System Monitor")
        window.set_default_size(1040, 720)
        window.add_css_class("swir-app")
        self.window = window

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        window.set_child(root)

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        header.add_css_class("swir-header")
        brand = Gtk.Label(label="◆  SWIR System Monitor")
        brand.add_css_class("swir-brand")
        brand.set_xalign(0)
        header.append(brand)
        root.append(header)

        notebook = Gtk.Notebook()
        notebook.set_hexpand(True)
        notebook.set_vexpand(True)
        root.append(notebook)

        overview = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        overview.set_margin_top(8)
        overview.set_margin_bottom(8)
        overview.set_margin_start(8)
        overview.set_margin_end(8)
        self.metrics = Gtk.Label()
        self.metrics.add_css_class("swir-metric")
        self.metrics.set_xalign(0)
        self.metrics.set_selectable(True)
        overview.append(self.metrics)

        process_toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.process_filter = Gtk.SearchEntry()
        self.process_filter.set_placeholder_text("Filter by process name or PID")
        self.process_filter.set_max_length(MAX_FILTER_CHARS)
        self.process_filter.set_hexpand(True)
        self.process_filter.add_css_class("swir-control")
        self.process_filter.connect("search-changed", self._on_process_filter_changed)
        process_toolbar.append(self.process_filter)

        self.end_process_button = Gtk.Button(label="End Process")
        self.end_process_button.add_css_class("swir-danger")
        self.end_process_button.set_sensitive(False)
        self.end_process_button.set_tooltip_text("Send SIGTERM to the selected process owned by your user")
        self.end_process_button.connect("clicked", self._on_end_process_clicked)
        process_toolbar.append(self.end_process_button)
        overview.append(process_toolbar)

        self.process_status = Gtk.Label(
            label="Select a process to inspect it. Ending a process requires confirmation and never elevates privileges."
        )
        self.process_status.add_css_class("swir-muted")
        self.process_status.set_xalign(0)
        self.process_status.set_wrap(True)
        overview.append(self.process_status)

        scroller = Gtk.ScrolledWindow()
        scroller.set_hexpand(True)
        scroller.set_vexpand(True)
        self.listbox = Gtk.ListBox()
        self.listbox.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.listbox.connect("row-selected", self._on_process_selected)
        scroller.set_child(self.listbox)
        overview.append(scroller)
        notebook.append_page(overview, Gtk.Label(label="Processes"))

        diagnostics = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        diagnostics.set_margin_top(8)
        diagnostics.set_margin_bottom(8)
        diagnostics.set_margin_start(8)
        diagnostics.set_margin_end(8)

        diag_toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.diag_summary = Gtk.Label(label="Diagnostics have not been refreshed yet.")
        self.diag_summary.add_css_class("swir-metric")
        self.diag_summary.set_xalign(0)
        self.diag_summary.set_hexpand(True)
        self.diag_summary.set_selectable(True)
        diag_toolbar.append(self.diag_summary)
        self.diag_refresh = Gtk.Button(label="Refresh diagnostics")
        self.diag_refresh.connect("clicked", self._on_refresh_diagnostics)
        diag_toolbar.append(self.diag_refresh)
        diagnostics.append(diag_toolbar)

        diag_scroller = Gtk.ScrolledWindow()
        diag_scroller.set_hexpand(True)
        diag_scroller.set_vexpand(True)
        self.diag_text = Gtk.TextView()
        self.diag_text.add_css_class("swir-diag")
        self.diag_text.set_editable(False)
        self.diag_text.set_cursor_visible(False)
        self.diag_text.set_monospace(True)
        self.diag_text.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        diag_scroller.set_child(self.diag_text)
        diagnostics.append(diag_scroller)
        notebook.append_page(diagnostics, Gtk.Label(label="Diagnostics"))

        self._refresh()
        self._refresh_diagnostics()
        GLib.timeout_add_seconds(2, self._refresh)
        window.connect("map", self._on_mapped)
        window.present()

    def _clear_rows(self) -> None:
        assert self.listbox is not None
        child = self.listbox.get_first_child()
        while child is not None:
            next_child = child.get_next_sibling()
            self.listbox.remove(child)
            child = next_child

    def _on_process_filter_changed(self, _entry: Gtk.SearchEntry) -> None:
        self._refresh()

    def _filtered_processes(self, processes: list[ProcessRow]) -> list[ProcessRow]:
        query = ""
        if self.process_filter is not None:
            query = self.process_filter.get_text().strip().casefold()[:MAX_FILTER_CHARS]
        if not query:
            return processes
        return [row for row in processes if query in row.name.casefold() or query in str(row.pid)]

    def _refresh(self) -> bool:
        assert self.metrics is not None and self.listbox is not None
        selected = self._selected_process()
        selected_identity = (selected.pid, selected.start_ticks) if selected else None
        try:
            mem = read_meminfo()
            uptime = read_uptime_seconds()
            load = os.getloadavg()
            processes = read_processes()
        except (OSError, ValueError) as exc:
            self.metrics.set_text(f"Could not read system metrics: {exc}")
            return True

        total = mem.get("MemTotal", 0)
        available = mem.get("MemAvailable", 0)
        used = max(0, total - available)
        self.last_process_count = len(processes)
        self.last_mem_total_kib = total
        visible = self._filtered_processes(processes)
        self.metrics.set_text(
            f"Memory {format_mib(used)} / {format_mib(total)}  •  "
            f"Load {load[0]:.2f} {load[1]:.2f} {load[2]:.2f}  •  "
            f"Uptime {uptime / 3600.0:.1f} h  •  Processes {len(processes)}"
        )

        self._clear_rows()
        reselection: Gtk.ListBoxRow | None = None
        for process in visible:
            row = Gtk.ListBoxRow()
            row.add_css_class("swir-row")
            row.swir_process = process  # type: ignore[attr-defined]
            box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
            pid = Gtk.Label(label=str(process.pid))
            pid.set_width_chars(8)
            pid.set_xalign(1)
            box.append(pid)
            name = Gtk.Label(label=process.name)
            name.set_xalign(0)
            name.set_hexpand(True)
            box.append(name)
            rss = Gtk.Label(label=format_mib(process.rss_kib))
            rss.add_css_class("swir-muted")
            rss.set_width_chars(14)
            rss.set_xalign(1)
            box.append(rss)
            row.set_child(box)
            self.listbox.append(row)
            if selected_identity == (process.pid, process.start_ticks):
                reselection = row
        if reselection is not None:
            self.listbox.select_row(reselection)
        else:
            self._set_end_button_sensitive(False)
        return True

    def _selected_process(self) -> ProcessRow | None:
        if self.listbox is None:
            return None
        row = self.listbox.get_selected_row()
        return getattr(row, "swir_process", None) if row is not None else None

    def _set_end_button_sensitive(self, enabled: bool) -> None:
        if self.end_process_button is not None:
            self.end_process_button.set_sensitive(enabled)

    def _on_process_selected(self, _listbox: Gtk.ListBox, row: Gtk.ListBoxRow | None) -> None:
        process = getattr(row, "swir_process", None) if row is not None else None
        if process is None:
            self._set_end_button_sensitive(False)
            return
        protected = _ancestor_pids()
        can_end = process.uid == os.getuid() and process.pid > 1 and process.pid not in protected
        self._set_end_button_sensitive(can_end)
        if self.process_status is not None:
            if can_end:
                self.process_status.set_text(
                    f"Selected PID {process.pid} • {process.name} • {format_mib(process.rss_kib)} • "
                    "End Process sends SIGTERM only after explicit confirmation."
                )
            else:
                self.process_status.set_text(
                    f"Selected PID {process.pid} • {process.name}. This process is protected or not owned by your user."
                )

    def _on_end_process_clicked(self, _button: Gtk.Button) -> None:
        process = self._selected_process()
        if process is None or self.window is None:
            return
        dialog = Gtk.MessageDialog(
            transient_for=self.window,
            modal=True,
            message_type=Gtk.MessageType.WARNING,
            buttons=Gtk.ButtonsType.NONE,
            text=f"End {process.name}?",
        )
        dialog.format_secondary_text(
            f"SWIR will send SIGTERM to PID {process.pid}. Unsaved work in that process may be lost. "
            "The action is limited to your user and the process identity is revalidated immediately before signaling."
        )
        dialog.add_button("Cancel", Gtk.ResponseType.CANCEL)
        dialog.add_button("End Process", Gtk.ResponseType.ACCEPT)
        dialog.connect("response", self._on_end_process_response, process)
        dialog.present()

    def _on_end_process_response(
        self, dialog: Gtk.MessageDialog, response: int, process: ProcessRow
    ) -> None:
        dialog.destroy()
        if response != Gtk.ResponseType.ACCEPT:
            if self.process_status is not None:
                self.process_status.set_text("Process termination cancelled. No signal was sent.")
            return
        try:
            terminate_same_user_process(process)
        except ProcessTerminationError as exc:
            if self.process_status is not None:
                self.process_status.set_text(f"Process was not ended: {exc}")
        else:
            if self.process_status is not None:
                self.process_status.set_text(
                    f"SIGTERM sent to PID {process.pid} ({process.name}). Refreshing process list."
                )
        self._refresh()

    def _on_refresh_diagnostics(self, _button: Gtk.Button) -> None:
        self._refresh_diagnostics()

    def _refresh_diagnostics(self) -> None:
        assert self.diag_summary is not None and self.diag_refresh is not None
        if self.diagnostics_running:
            return
        self.diagnostics_running = True
        self.diagnostics_ready = False
        self.diag_refresh.set_sensitive(False)
        self.diag_summary.set_text("Refreshing bounded read-only diagnostics…")
        threading.Thread(target=self._collect_diagnostics, name="swir-diagnostics", daemon=True).start()

    def _collect_diagnostics(self) -> None:
        try:
            uptime = read_uptime_seconds()
        except (OSError, ValueError):
            uptime = 0.0
        snapshot = DiagnosticsSnapshot(
            os_name=read_os_release(),
            kernel_version=read_kernel_version(),
            uptime_seconds=uptime,
            failed=run_read_only_command(FAILED_UNITS_COMMAND),
            journal=run_read_only_command(JOURNAL_WARNINGS_COMMAND),
        )
        GLib.idle_add(self._apply_diagnostics, snapshot)

    def _apply_diagnostics(self, snapshot: DiagnosticsSnapshot) -> bool:
        assert self.diag_summary is not None and self.diag_text is not None and self.diag_refresh is not None
        failed_lines = (
            _nonempty_lines(snapshot.failed.stdout, MAX_PROCESS_ROWS)
            if snapshot.failed.status == "ok"
            else []
        )
        journal_lines = (
            _nonempty_lines(snapshot.journal.stdout, JOURNAL_LINE_LIMIT)
            if snapshot.journal.status == "ok"
            else []
        )
        self.failed_units_status = snapshot.failed.status
        self.journal_status = snapshot.journal.status
        self.failed_units_count = len(failed_lines)
        self.journal_visible_line_count = len(journal_lines)
        self.diagnostics_running = False
        self.diagnostics_ready = True
        self.diag_refresh.set_sensitive(True)

        self.diag_summary.set_text(
            f"Read-only diagnostics  •  failed units: {snapshot.failed.status} ({len(failed_lines)})  •  "
            f"boot journal: {snapshot.journal.status} ({len(journal_lines)} visible lines)"
        )
        failed_body = (
            "\n".join(failed_lines)
            if failed_lines
            else f"[{snapshot.failed.status}] No readable failed-unit rows."
        )
        journal_body = (
            "\n".join(journal_lines)
            if journal_lines
            else f"[{snapshot.journal.status}] No readable warning/error rows."
        )
        body = (
            "SWIR OS Diagnostics — read only\n"
            f"OS: {snapshot.os_name}\n"
            f"Kernel: {snapshot.kernel_version}\n"
            f"Uptime: {snapshot.uptime_seconds / 3600.0:.1f} h\n\n"
            f"Failed systemd units ({snapshot.failed.status}):\n{failed_body}\n\n"
            f"Recent boot warnings/errors — last {JOURNAL_LINE_LIMIT} lines max ({snapshot.journal.status}):\n"
            f"{journal_body}\n\n"
            "Safety: fixed absolute command paths, no shell, no elevation, bounded timeout/output. "
            "The separate Processes tab may send same-user SIGTERM after explicit confirmation."
        )
        self.diag_text.get_buffer().set_text(body[:MAX_COMMAND_OUTPUT_CHARS])
        return False

    def _on_mapped(self, _window: Gtk.Window) -> None:
        if not self.e2e or not self.evidence_path:
            return
        GLib.timeout_add(100, self._write_e2e_when_ready)

    def _write_e2e_when_ready(self) -> bool:
        if self.evidence_written:
            return False
        if not self.diagnostics_ready:
            return True
        path = pathlib.Path(self.evidence_path)
        runtime_text = os.environ.get("XDG_RUNTIME_DIR", "")
        if not runtime_text or path.parent.resolve() != pathlib.Path(runtime_text).resolve():
            raise RuntimeError("refusing SWIR System Monitor evidence path outside XDG_RUNTIME_DIR")
        payload = {
            "schema": EVIDENCE_SCHEMA,
            "passed": self.last_process_count > 0 and self.last_mem_total_kib > 0,
            "applicationId": APP_ID,
            "nativeToolkit": "gtk4",
            "displayProtocol": "wayland",
            "windowMapped": True,
            "privilegedOperations": False,
            "processRowsBounded": MAX_PROCESS_ROWS,
            "visibleProcessCount": self.last_process_count,
            "memTotalKiB": self.last_mem_total_kib,
            "processFilterMaxChars": MAX_FILTER_CHARS,
            "processTerminationEnabled": True,
            "processTerminationSignal": "SIGTERM",
            "processTerminationSameUidOnly": True,
            "processTerminationRequiresConfirmation": True,
            "processIdentityRevalidated": True,
            "processAncestorProtection": True,
            "processTerminationUsesShell": False,
            "processTerminationElevates": False,
            "pidfdPreferred": hasattr(os, "pidfd_open") and hasattr(signal, "pidfd_send_signal"),
            "diagnosticsReadOnly": True,
            "diagnosticsShell": False,
            "diagnosticsAsync": True,
            "systemctlAbsolutePath": SYSTEMCTL_PATH,
            "journalctlAbsolutePath": JOURNALCTL_PATH,
            "diagnosticsCommandTimeoutSeconds": COMMAND_TIMEOUT_SECONDS,
            "diagnosticsOutputMaxChars": MAX_COMMAND_OUTPUT_CHARS,
            "journalLineLimit": JOURNAL_LINE_LIMIT,
            "failedUnitsStatus": self.failed_units_status,
            "journalStatus": self.journal_status,
            "failedUnitsCount": self.failed_units_count,
            "journalVisibleLineCount": self.journal_visible_line_count,
            "evidenceIncludesLogContent": False,
        }
        path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
        path.chmod(0o600)
        self.evidence_written = True
        GLib.timeout_add(250, self._finish_e2e)
        return False

    def _finish_e2e(self) -> bool:
        self.quit()
        return False


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        raise SystemExit(_self_test())
    raise SystemExit(SwirSystemMonitor().run(sys.argv))
