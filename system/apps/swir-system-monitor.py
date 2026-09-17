#!/usr/bin/env python3
"""SWIR System Monitor — first-party native GTK4 process/resource viewer."""

from __future__ import annotations

import json
import os
import pathlib
import sys
from dataclasses import dataclass
from typing import Final

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gdk, GLib, Gtk  # noqa: E402

APP_ID: Final = "dev.swir.SystemMonitor"
EVIDENCE_SCHEMA: Final = "swir.native-system-monitor-runtime-evidence/0.1"
MAX_PROCESS_ROWS: Final = 200

CSS = b"""
window.swir-app { background: #02050A; color: #F4FAFF; }
.swir-header { background: #07111C; border-bottom: 1px solid #0088FF; padding: 10px 14px; }
.swir-brand { color: #62E5FF; font-size: 18px; font-weight: 800; }
.swir-muted { color: #8DA8B8; }
.swir-metric { background: #07111C; border: 1px solid rgba(98,229,255,0.28); border-radius: 12px; padding: 10px 14px; }
.swir-row { padding: 7px 10px; border-bottom: 1px solid rgba(98,229,255,0.08); }
"""


@dataclass(frozen=True)
class ProcessRow:
    pid: int
    name: str
    rss_kib: int


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


class SwirSystemMonitor(Gtk.Application):
    def __init__(self) -> None:
        super().__init__(application_id=APP_ID)
        self.window: Gtk.ApplicationWindow | None = None
        self.metrics: Gtk.Label | None = None
        self.listbox: Gtk.ListBox | None = None
        self.e2e = os.environ.get("SWIR_APP_E2E", "0") == "1"
        self.evidence_path = os.environ.get("SWIR_APP_EVIDENCE_PATH", "")
        self.last_process_count = 0
        self.last_mem_total_kib = 0

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

        self.metrics = Gtk.Label()
        self.metrics.add_css_class("swir-metric")
        self.metrics.set_xalign(0)
        self.metrics.set_selectable(True)
        root.append(self.metrics)

        scroller = Gtk.ScrolledWindow()
        scroller.set_hexpand(True)
        scroller.set_vexpand(True)
        self.listbox = Gtk.ListBox()
        self.listbox.set_selection_mode(Gtk.SelectionMode.NONE)
        scroller.set_child(self.listbox)
        root.append(scroller)

        self._refresh()
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
        }
        path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
        path.chmod(0o600)
        GLib.timeout_add(250, self._finish_e2e)

    def _finish_e2e(self) -> bool:
        self.quit()
        return False


if __name__ == "__main__":
    raise SystemExit(SwirSystemMonitor().run(sys.argv))
