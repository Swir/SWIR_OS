#!/usr/bin/env python3
"""SWIR System Monitor — first-party native GTK4 process/resource and diagnostics viewer."""

from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
from dataclasses import dataclass
from typing import Final

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gdk, GLib, Gtk  # noqa: E402

APP_ID: Final = "dev.swir.SystemMonitor"
EVIDENCE_SCHEMA: Final = "swir.native-system-monitor-runtime-evidence/0.1"
MAX_PROCESS_ROWS: Final = 200
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

CSS = b"""
window.swir-app { background: #02050A; color: #F4FAFF; }
.swir-header { background: #07111C; border-bottom: 1px solid #0088FF; padding: 10px 14px; }
.swir-brand { color: #62E5FF; font-size: 18px; font-weight: 800; }
.swir-muted { color: #8DA8B8; }
.swir-metric { background: #07111C; border: 1px solid rgba(98,229,255,0.28); border-radius: 12px; padding: 10px 14px; }
.swir-row { padding: 7px 10px; border-bottom: 1px solid rgba(98,229,255,0.08); }
.swir-diag { background: #07111C; border: 1px solid rgba(98,229,255,0.18); border-radius: 12px; padding: 12px; }
"""


@dataclass(frozen=True)
class ProcessRow:
    pid: int
    name: str
    rss_kib: int


@dataclass(frozen=True)
class CommandResult:
    status: str
    returncode: int | None
    stdout: str
    stderr: str


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


def read_processes(limit: int = MAX_PROCESS_ROWS) -> list[ProcessRow]:
    rows: list[ProcessRow] = []
    for entry in pathlib.Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        pid = int(entry.name)
        try:
            name = (entry / "comm").read_text(encoding="utf-8").strip()
            rss_kib = 0
            with (entry / "status").open(encoding="utf-8") as handle:
                for line in handle:
                    if line.startswith("VmRSS:"):
                        parts = line.split()
                        if len(parts) >= 2 and parts[1].isdigit():
                            rss_kib = int(parts[1])
                        break
        except (FileNotFoundError, PermissionError, ProcessLookupError, OSError, UnicodeError):
            continue
        rows.append(ProcessRow(pid=pid, name=name[:120], rss_kib=rss_kib))
    rows.sort(key=lambda row: (-row.rss_kib, row.pid))
    return rows[:limit]


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
    env = {
        "PATH": "/usr/bin:/bin",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
    }
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
            "timeout",
            None,
            stdout[:MAX_COMMAND_OUTPUT_CHARS],
            stderr[:MAX_COMMAND_OUTPUT_CHARS],
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


class SwirSystemMonitor(Gtk.Application):
    def __init__(self) -> None:
        super().__init__(application_id=APP_ID)
        self.window: Gtk.ApplicationWindow | None = None
        self.metrics: Gtk.Label | None = None
        self.listbox: Gtk.ListBox | None = None
        self.diag_summary: Gtk.Label | None = None
        self.diag_text: Gtk.TextView | None = None
        self.e2e = os.environ.get("SWIR_APP_E2E", "0") == "1"
        self.evidence_path = os.environ.get("SWIR_APP_EVIDENCE_PATH", "")
        self.last_process_count = 0
        self.last_mem_total_kib = 0
        self.failed_units_status = "not-run"
        self.journal_status = "not-run"
        self.failed_units_count = 0
        self.journal_visible_line_count = 0

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
        window.set_default_size(980, 680)
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

        scroller = Gtk.ScrolledWindow()
        scroller.set_hexpand(True)
        scroller.set_vexpand(True)
        self.listbox = Gtk.ListBox()
        self.listbox.set_selection_mode(Gtk.SelectionMode.NONE)
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
        refresh_diag = Gtk.Button(label="Refresh diagnostics")
        refresh_diag.connect("clicked", self._on_refresh_diagnostics)
        diag_toolbar.append(refresh_diag)
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

    def _refresh(self) -> bool:
        assert self.metrics is not None and self.listbox is not None
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
        self.metrics.set_text(
            f"Memory {format_mib(used)} / {format_mib(total)}  •  "
            f"Load {load[0]:.2f} {load[1]:.2f} {load[2]:.2f}  •  "
            f"Uptime {uptime / 3600.0:.1f} h"
        )

        self._clear_rows()
        for process in processes:
            row = Gtk.ListBoxRow()
            row.add_css_class("swir-row")
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
        return True

    def _on_refresh_diagnostics(self, _button: Gtk.Button) -> None:
        self._refresh_diagnostics()

    def _refresh_diagnostics(self) -> None:
        assert self.diag_summary is not None and self.diag_text is not None
        failed = run_read_only_command(FAILED_UNITS_COMMAND)
        journal = run_read_only_command(JOURNAL_WARNINGS_COMMAND)
        self.failed_units_status = failed.status
        self.journal_status = journal.status
        failed_lines = _nonempty_lines(failed.stdout, MAX_PROCESS_ROWS) if failed.status == "ok" else []
        journal_lines = _nonempty_lines(journal.stdout, JOURNAL_LINE_LIMIT) if journal.status == "ok" else []
        self.failed_units_count = len(failed_lines)
        self.journal_visible_line_count = len(journal_lines)

        try:
            uptime = read_uptime_seconds()
        except (OSError, ValueError):
            uptime = 0.0

        self.diag_summary.set_text(
            f"Read-only diagnostics  •  failed units: {failed.status} ({len(failed_lines)})  •  "
            f"boot journal: {journal.status} ({len(journal_lines)} visible lines)"
        )
        failed_body = "\n".join(failed_lines) if failed_lines else f"[{failed.status}] No readable failed-unit rows."
        journal_body = "\n".join(journal_lines) if journal_lines else f"[{journal.status}] No readable warning/error rows."
        body = (
            "SWIR OS Diagnostics — read only\n"
            f"OS: {read_os_release()}\n"
            f"Kernel: {read_kernel_version()}\n"
            f"Uptime: {uptime / 3600.0:.1f} h\n\n"
            f"Failed systemd units ({failed.status}):\n{failed_body}\n\n"
            f"Recent boot warnings/errors — last {JOURNAL_LINE_LIMIT} lines max ({journal.status}):\n"
            f"{journal_body}\n\n"
            "Safety: fixed absolute command paths, no shell, no elevation, bounded timeout/output."
        )
        self.diag_text.get_buffer().set_text(body[:MAX_COMMAND_OUTPUT_CHARS])

    def _on_mapped(self, _window: Gtk.Window) -> None:
        if not self.e2e or not self.evidence_path:
            return
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
            "diagnosticsReadOnly": True,
            "diagnosticsShell": False,
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
        GLib.timeout_add(250, self._finish_e2e)

    def _finish_e2e(self) -> bool:
        self.quit()
        return False


if __name__ == "__main__":
    raise SystemExit(SwirSystemMonitor().run(sys.argv))
