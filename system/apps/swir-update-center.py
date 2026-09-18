#!/usr/bin/env python3
"""SWIR Update Center — native read-only update planning surface.

This UI reads the locally available APT metadata and asks apt-get for a
non-mutating simulation. It intentionally does not refresh repositories or
apply packages itself. Real updates must flow through SWIR's existing
journaled, privileged package transaction service and policy boundary.
"""

from __future__ import annotations

import json
import os
import pathlib
import sys
import threading
from typing import Final

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gdk, GLib, Gtk  # noqa: E402

LIBDIR = pathlib.Path("/usr/local/lib/swir")
if LIBDIR.is_dir() and str(LIBDIR) not in sys.path:
    sys.path.insert(0, str(LIBDIR))

from package_status_runtime import MAX_UPDATE_ROWS, UpdateSnapshot, read_update_snapshot, tools_status  # noqa: E402

APP_ID: Final = "dev.swir.UpdateCenter"
EVIDENCE_SCHEMA: Final = "swir.native-update-center-runtime-evidence/0.1"

CSS = b"""
window.swir-app { background: #02050A; color: #F4FAFF; }
.swir-header { background: #07111C; border-bottom: 1px solid #0088FF; padding: 10px 14px; }
.swir-brand { color: #62E5FF; font-size: 18px; font-weight: 800; }
.swir-muted { color: #8DA8B8; }
.swir-status { background: #07111C; border: 1px solid rgba(98,229,255,0.28); border-radius: 12px; padding: 10px 14px; }
.swir-row { padding: 8px 10px; border-bottom: 1px solid rgba(98,229,255,0.08); }
.swir-name { color: #EAF9FF; font-weight: 700; }
.swir-button { background: #07111C; color: #F4FAFF; border: 1px solid #0088FF; border-radius: 10px; padding: 7px 12px; }
.swir-button:hover { border-color: #62E5FF; }
"""


class SwirUpdateCenter(Gtk.Application):
    def __init__(self) -> None:
        super().__init__(application_id=APP_ID)
        self.window: Gtk.ApplicationWindow | None = None
        self.listbox: Gtk.ListBox | None = None
        self.status_label: Gtk.Label | None = None
        self.generation = 0
        self.visible_rows = 0
        self.last_query_ok = False
        self.last_truncated = False
        self.e2e = os.environ.get("SWIR_APP_E2E", "0") == "1"
        self.evidence_path = os.environ.get("SWIR_APP_EVIDENCE_PATH", "")

    def do_startup(self) -> None:
        Gtk.Application.do_startup(self)
        provider = Gtk.CssProvider()
        provider.load_from_data(CSS)
        display = Gdk.Display.get_default()
        if display is None:
            raise RuntimeError("SWIR Update Center requires a graphical display")
        Gtk.StyleContext.add_provider_for_display(display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    def do_activate(self) -> None:
        if self.window is not None:
            self.window.present()
            return

        window = Gtk.ApplicationWindow(application=self)
        window.set_title("SWIR Update Center")
        window.set_default_size(1000, 700)
        window.add_css_class("swir-app")
        self.window = window

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        window.set_child(root)

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        header.add_css_class("swir-header")
        brand = Gtk.Label(label="◆  SWIR Update Center")
        brand.add_css_class("swir-brand")
        brand.set_xalign(0)
        header.append(brand)
        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        header.append(spacer)
        refresh = Gtk.Button(label="Re-check local metadata")
        refresh.add_css_class("swir-button")
        refresh.connect("clicked", self._refresh_clicked)
        header.append(refresh)
        root.append(header)

        self.status_label = Gtk.Label(label="Calculating a non-destructive update preview…", wrap=True)
        self.status_label.set_xalign(0)
        self.status_label.set_margin_start(12)
        self.status_label.set_margin_end(12)
        self.status_label.add_css_class("swir-status")
        root.append(self.status_label)

        explanation = Gtk.Label(
            label=(
                "This view uses the package metadata already present on the system. "
                "It does not refresh repositories and it cannot apply changes."
            ),
            wrap=True,
        )
        explanation.add_css_class("swir-muted")
        explanation.set_xalign(0)
        explanation.set_margin_start(12)
        explanation.set_margin_end(12)
        root.append(explanation)

        scroller = Gtk.ScrolledWindow()
        scroller.set_hexpand(True)
        scroller.set_vexpand(True)
        self.listbox = Gtk.ListBox()
        self.listbox.set_selection_mode(Gtk.SelectionMode.NONE)
        scroller.set_child(self.listbox)
        root.append(scroller)

        footer = Gtk.Label(
            label="Apply/rollback is intentionally absent here until wired through the journaled privileged transaction service.",
            wrap=True,
        )
        footer.add_css_class("swir-muted")
        footer.set_xalign(0)
        footer.set_margin_start(12)
        footer.set_margin_end(12)
        footer.set_margin_bottom(8)
        root.append(footer)

        window.connect("map", self._on_mapped)
        window.present()
        self._refresh()

    def _clear_rows(self) -> None:
        assert self.listbox is not None
        child = self.listbox.get_first_child()
        while child is not None:
            next_child = child.get_next_sibling()
            self.listbox.remove(child)
            child = next_child

    def _refresh_clicked(self, _button: Gtk.Button) -> None:
        self._refresh()

    def _refresh(self) -> None:
        assert self.status_label is not None
        self.generation += 1
        generation = self.generation
        self.status_label.set_text("Calculating a non-destructive update preview…")

        def run() -> None:
            snapshot = read_update_snapshot()
            GLib.idle_add(self._finish_refresh, generation, snapshot)

        threading.Thread(target=run, name="swir-update-preview", daemon=True).start()

    def _finish_refresh(self, generation: int, snapshot: UpdateSnapshot) -> bool:
        if generation != self.generation:
            return False
        assert self.status_label is not None and self.listbox is not None
        self._clear_rows()
        self.last_query_ok = snapshot.ok
        self.last_truncated = snapshot.truncated
        self.visible_rows = len(snapshot.rows)

        if not snapshot.ok:
            self.status_label.set_text(f"Update preview unavailable: {snapshot.message}")
            return False

        if not snapshot.rows:
            self.status_label.set_text(snapshot.message)
            return False

        suffix = f" • first {MAX_UPDATE_ROWS} shown" if snapshot.truncated else ""
        self.status_label.set_text(f"{len(snapshot.rows)} package upgrades in the local simulation{suffix}")
        for update in snapshot.rows:
            row = Gtk.ListBoxRow()
            row.add_css_class("swir-row")
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            name = Gtk.Label(label=update.name)
            name.add_css_class("swir-name")
            name.set_xalign(0)
            name.set_selectable(True)
            box.append(name)
            versions = Gtk.Label(label=f"{update.current_version}  →  {update.candidate_version}", ellipsize=3)
            versions.add_css_class("swir-muted")
            versions.set_xalign(0)
            versions.set_tooltip_text(f"{update.current_version} → {update.candidate_version}")
            box.append(versions)
            row.set_child(box)
            self.listbox.append(row)
        return False

    def _on_mapped(self, _window: Gtk.Window) -> None:
        if not self.e2e or not self.evidence_path:
            return
        path = pathlib.Path(self.evidence_path)
        runtime_text = os.environ.get("XDG_RUNTIME_DIR", "")
        if not runtime_text or path.parent.resolve() != pathlib.Path(runtime_text).resolve():
            raise RuntimeError("refusing Update Center evidence path outside XDG_RUNTIME_DIR")
        status = tools_status()
        payload = {
            "schema": EVIDENCE_SCHEMA,
            "passed": status["aptGet"],
            "applicationId": APP_ID,
            "nativeToolkit": "gtk4",
            "displayProtocol": "wayland",
            "windowMapped": True,
            "privilegedOperations": False,
            "mutationControlsExposed": False,
            "repositoryRefreshPerformed": False,
            "packageTransactionBrokerBypassed": False,
            "simulationOnly": True,
            "updateRowsBounded": MAX_UPDATE_ROWS,
            "tools": status,
        }
        path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
        path.chmod(0o600)
        GLib.timeout_add(350, self._finish_e2e)

    def _finish_e2e(self) -> bool:
        self.quit()
        return False


if __name__ == "__main__":
    raise SystemExit(SwirUpdateCenter().run(sys.argv))
