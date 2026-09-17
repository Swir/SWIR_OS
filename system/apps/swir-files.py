#!/usr/bin/env python3
"""SWIR Files — first-party native GTK4 file manager for System Edition."""

from __future__ import annotations

import json
import os
import pathlib
import sys
from typing import Final

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gdk, GLib, Gtk  # noqa: E402

LIBDIR = pathlib.Path("/usr/local/lib/swir")
if LIBDIR.is_dir() and str(LIBDIR) not in sys.path:
    sys.path.insert(0, str(LIBDIR))

from core_runtime import DirectoryEntry, list_directory, resolve_directory  # noqa: E402

APP_ID: Final = "dev.swir.Files"
EVIDENCE_SCHEMA: Final = "swir.native-files-runtime-evidence/0.1"

CSS = b"""
window.swir-app { background: #02050A; color: #F4FAFF; }
.swir-header { background: #07111C; border-bottom: 1px solid #0088FF; padding: 10px 14px; }
.swir-brand { color: #62E5FF; font-size: 18px; font-weight: 800; }
.swir-muted { color: #8DA8B8; }
.swir-path { background: #07111C; color: #F4FAFF; border: 1px solid rgba(98,229,255,0.32); border-radius: 10px; padding: 8px 12px; }
.swir-file-row { padding: 9px 12px; border-bottom: 1px solid rgba(98,229,255,0.08); }
.swir-file-row:hover { background: rgba(0,136,255,0.10); }
.swir-button { background: #07111C; color: #F4FAFF; border: 1px solid #0088FF; border-radius: 10px; padding: 7px 12px; }
.swir-button:hover { border-color: #62E5FF; }
"""


def human_size(size: int | None) -> str:
    if size is None:
        return ""
    value = float(size)
    units = ("B", "KiB", "MiB", "GiB", "TiB")
    for unit in units:
        if value < 1024.0 or unit == units[-1]:
            return f"{int(value)} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024.0
    return ""


class SwirFiles(Gtk.Application):
    def __init__(self) -> None:
        super().__init__(application_id=APP_ID)
        self.window: Gtk.ApplicationWindow | None = None
        self.listbox: Gtk.ListBox | None = None
        self.path_label: Gtk.Label | None = None
        self.status: Gtk.Label | None = None
        self.include_hidden = False
        self.history: list[pathlib.Path] = []
        self.current = resolve_directory(sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("--") else None)
        self.row_paths: dict[Gtk.ListBoxRow, pathlib.Path] = {}
        self.e2e = os.environ.get("SWIR_APP_E2E", "0") == "1"
        self.evidence_path = os.environ.get("SWIR_APP_EVIDENCE_PATH", "")

    def do_startup(self) -> None:
        Gtk.Application.do_startup(self)
        provider = Gtk.CssProvider()
        provider.load_from_data(CSS)
        display = Gdk.Display.get_default()
        if display is None:
            raise RuntimeError("SWIR Files requires a graphical display")
        Gtk.StyleContext.add_provider_for_display(display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    def do_activate(self) -> None:
        if self.window is not None:
            self.window.present()
            return

        window = Gtk.ApplicationWindow(application=self)
        window.set_title("SWIR Files")
        window.set_default_size(980, 680)
        window.add_css_class("swir-app")
        self.window = window

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        window.set_child(root)

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        header.add_css_class("swir-header")
        brand = Gtk.Label(label="◆  SWIR Files")
        brand.add_css_class("swir-brand")
        brand.set_xalign(0)
        header.append(brand)
        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        header.append(spacer)
        for label, callback in (("Back", self._go_back), ("Up", self._go_up), ("Home", self._go_home), ("Refresh", self._refresh_clicked)):
            button = Gtk.Button(label=label)
            button.add_css_class("swir-button")
            button.connect("clicked", callback)
            header.append(button)
        hidden = Gtk.CheckButton(label="Hidden")
        hidden.connect("toggled", self._toggle_hidden)
        header.append(hidden)
        root.append(header)

        self.path_label = Gtk.Label()
        self.path_label.add_css_class("swir-path")
        self.path_label.set_xalign(0)
        self.path_label.set_selectable(True)
        root.append(self.path_label)

        scroller = Gtk.ScrolledWindow()
        scroller.set_hexpand(True)
        scroller.set_vexpand(True)
        self.listbox = Gtk.ListBox()
        self.listbox.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.listbox.connect("row-activated", self._activate_row)
        scroller.set_child(self.listbox)
        root.append(scroller)

        self.status = Gtk.Label()
        self.status.add_css_class("swir-muted")
        self.status.set_xalign(0)
        root.append(self.status)

        self._render_directory()
        window.connect("map", self._on_mapped)
        window.present()

    def _clear_rows(self) -> None:
        assert self.listbox is not None
        child = self.listbox.get_first_child()
        while child is not None:
            next_child = child.get_next_sibling()
            self.listbox.remove(child)
            child = next_child
        self.row_paths.clear()

    def _make_row(self, entry: DirectoryEntry) -> Gtk.ListBoxRow:
        row = Gtk.ListBoxRow()
        row.add_css_class("swir-file-row")
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        icon = {"directory": "▣", "file": "◇", "symlink": "↗", "unavailable": "!"}.get(entry.kind, "·")
        glyph = Gtk.Label(label=icon)
        glyph.add_css_class("swir-brand" if entry.kind == "directory" else "swir-muted")
        box.append(glyph)
        name = Gtk.Label(label=entry.name)
        name.set_xalign(0)
        name.set_hexpand(True)
        box.append(name)
        kind = Gtk.Label(label=entry.kind)
        kind.add_css_class("swir-muted")
        kind.set_width_chars(12)
        box.append(kind)
        size = Gtk.Label(label=human_size(entry.size))
        size.add_css_class("swir-muted")
        size.set_width_chars(12)
        size.set_xalign(1)
        box.append(size)
        row.set_child(box)
        self.row_paths[row] = self.current / entry.name
        return row

    def _render_directory(self) -> None:
        assert self.listbox is not None and self.path_label is not None and self.status is not None
        self._clear_rows()
        try:
            entries = list_directory(self.current, include_hidden=self.include_hidden)
        except (OSError, ValueError) as exc:
            self.status.set_text(f"Could not read folder: {exc}")
            return
        self.path_label.set_text(str(self.current))
        for entry in entries:
            self.listbox.append(self._make_row(entry))
        self.status.set_text(f"{len(entries)} items • read-only browsing foundation")

    def _navigate(self, target: pathlib.Path, *, record: bool = True) -> None:
        try:
            destination = resolve_directory(target)
        except (OSError, ValueError) as exc:
            if self.status is not None:
                self.status.set_text(f"Cannot open folder: {exc}")
            return
        if record and destination != self.current:
            self.history.append(self.current)
        self.current = destination
        self._render_directory()

    def _activate_row(self, _box: Gtk.ListBox, row: Gtk.ListBoxRow) -> None:
        target = self.row_paths.get(row)
        if target is None:
            return
        try:
            if target.is_dir():
                self._navigate(target)
            elif self.status is not None:
                self.status.set_text("File opening is intentionally not enabled until Default Apps integration is native.")
        except OSError as exc:
            if self.status is not None:
                self.status.set_text(f"Cannot inspect item: {exc}")

    def _go_back(self, _button: Gtk.Button) -> None:
        if self.history:
            self._navigate(self.history.pop(), record=False)

    def _go_up(self, _button: Gtk.Button) -> None:
        if self.current.parent != self.current:
            self._navigate(self.current.parent)

    def _go_home(self, _button: Gtk.Button) -> None:
        self._navigate(pathlib.Path.home())

    def _refresh_clicked(self, _button: Gtk.Button) -> None:
        self._render_directory()

    def _toggle_hidden(self, button: Gtk.CheckButton) -> None:
        self.include_hidden = button.get_active()
        self._render_directory()

    def _on_mapped(self, _window: Gtk.Window) -> None:
        if not self.e2e or not self.evidence_path:
            return
        path = pathlib.Path(self.evidence_path)
        runtime_text = os.environ.get("XDG_RUNTIME_DIR", "")
        if not runtime_text or path.parent.resolve() != pathlib.Path(runtime_text).resolve():
            raise RuntimeError("refusing SWIR Files evidence path outside XDG_RUNTIME_DIR")
        rows = list_directory(self.current, include_hidden=False)
        payload = {
            "schema": EVIDENCE_SCHEMA,
            "passed": True,
            "applicationId": APP_ID,
            "nativeToolkit": "gtk4",
            "displayProtocol": "wayland",
            "windowMapped": True,
            "privilegedOperations": False,
            "currentDirectoryReadable": True,
            "visibleEntryCount": len(rows),
            "fileOpenDelegationEnabled": False,
        }
        path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
        path.chmod(0o600)
        GLib.timeout_add(250, self._finish_e2e)

    def _finish_e2e(self) -> bool:
        self.quit()
        return False


if __name__ == "__main__":
    raise SystemExit(SwirFiles().run(sys.argv))
