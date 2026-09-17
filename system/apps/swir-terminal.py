#!/usr/bin/env python3
"""SWIR Terminal — first-party native VTE/GTK4 terminal for System Edition."""

from __future__ import annotations

import json
import os
import pathlib
import pwd
import sys
from typing import Final

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Vte", "3.91")
from gi.repository import Gdk, GLib, Gtk, Vte  # noqa: E402

APP_ID: Final = "dev.swir.Terminal"
EVIDENCE_SCHEMA: Final = "swir.native-terminal-runtime-evidence/0.1"

CSS = b"""
window.swir-app { background: #02050A; color: #F4FAFF; }
.swir-header { background: #07111C; border-bottom: 1px solid #0088FF; padding: 8px 12px; }
.swir-brand { color: #62E5FF; font-size: 18px; font-weight: 800; }
.swir-muted { color: #8DA8B8; }
.swir-error { color: #FF9D9D; }
"""


def resolve_login_shell() -> str:
    """Resolve the account shell without executing user-controlled shell text."""

    candidates: list[str] = []
    try:
        candidates.append(pwd.getpwuid(os.getuid()).pw_shell)
    except KeyError:
        pass
    candidates.extend(("/bin/bash", "/bin/sh"))
    for candidate in candidates:
        path = pathlib.Path(candidate)
        if path.is_absolute() and path.is_file() and os.access(path, os.X_OK):
            return str(path)
    raise RuntimeError("no executable login shell is available")


def spawn_terminal_child(terminal: Vte.Terminal, working_directory: str, argv: list[str]) -> str:
    """Spawn a shell across the VTE 0.76 and Debian 13 / VTE 0.80 GI bindings.

    Ubuntu 24.04 ships VTE 0.76 whose GI wrapper requires the closure/user-data
    parameters positionally, while Debian 13 ships VTE 0.80 where the annotated
    keyword form is available. A TypeError is raised before any child is spawned,
    so it is safe to retry with the legacy positional ABI only for that case.
    """

    try:
        terminal.spawn_async(
            pty_flags=Vte.PtyFlags.DEFAULT,
            working_directory=working_directory,
            argv=argv,
            envv=None,
            spawn_flags=GLib.SpawnFlags.DEFAULT,
            child_setup=None,
            timeout=-1,
            cancellable=None,
            callback=None,
        )
        return "annotated-keyword"
    except TypeError as keyword_error:
        try:
            # VTE 0.76 / PyGObject exposes child_setup_data and callback user_data
            # as positional parameters while hiding the destroy notifier.
            terminal.spawn_async(
                Vte.PtyFlags.DEFAULT,
                working_directory,
                argv,
                None,
                GLib.SpawnFlags.DEFAULT,
                None,
                None,
                -1,
                None,
                None,
                None,
            )
            return "vte076-positional"
        except TypeError as positional_error:
            version = f"{Vte.get_major_version()}.{Vte.get_minor_version()}.{Vte.get_micro_version()}"
            raise RuntimeError(
                "unsupported VTE spawn_async GI binding "
                f"(runtime {version}); keyword call: {keyword_error}; positional call: {positional_error}"
            ) from positional_error


class SwirTerminal(Gtk.Application):
    def __init__(self) -> None:
        super().__init__(application_id=APP_ID)
        self.window: Gtk.ApplicationWindow | None = None
        self.terminal: Vte.Terminal | None = None
        self.status: Gtk.Label | None = None
        self.e2e = os.environ.get("SWIR_APP_E2E", "0") == "1"
        self.evidence_path = os.environ.get("SWIR_APP_EVIDENCE_PATH", "")
        self.window_mapped = False
        self.spawn_requested = False
        self.evidence_written = False
        self.spawn_api = "not-attempted"
        self.spawn_error = ""
        self.shell_path = resolve_login_shell()

    def do_startup(self) -> None:
        Gtk.Application.do_startup(self)
        provider = Gtk.CssProvider()
        provider.load_from_data(CSS)
        display = Gdk.Display.get_default()
        if display is None:
            raise RuntimeError("SWIR Terminal requires a graphical display")
        Gtk.StyleContext.add_provider_for_display(display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    def do_activate(self) -> None:
        if self.window is not None:
            self.window.present()
            return

        window = Gtk.ApplicationWindow(application=self)
        window.set_title("SWIR Terminal")
        window.set_default_size(980, 650)
        window.add_css_class("swir-app")
        self.window = window

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        window.set_child(root)

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        header.add_css_class("swir-header")
        brand = Gtk.Label(label="◆  SWIR Terminal")
        brand.add_css_class("swir-brand")
        brand.set_xalign(0)
        header.append(brand)
        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        header.append(spacer)
        self.status = Gtk.Label(label="User shell • no privilege shortcut")
        self.status.add_css_class("swir-muted")
        header.append(self.status)
        root.append(header)

        terminal = Vte.Terminal()
        terminal.set_hexpand(True)
        terminal.set_vexpand(True)
        terminal.set_scrollback_lines(10000)
        terminal.set_mouse_autohide(True)
        terminal.connect("child-exited", self._on_child_exited)
        self.terminal = terminal
        root.append(terminal)

        argv = [self.shell_path]
        if self.e2e:
            argv = [self.shell_path, "-c", "printf 'SWIR Terminal E2E\\n'; sleep 3"]

        try:
            self.spawn_api = spawn_terminal_child(terminal, str(pathlib.Path.home()), argv)
            self.spawn_requested = True
        except (RuntimeError, GLib.Error, OSError) as exc:
            self.spawn_error = str(exc)[:500]
            self.status.set_text("Unable to start the user shell")
            self.status.remove_css_class("swir-muted")
            self.status.add_css_class("swir-error")
            print(f"SWIR Terminal spawn failed: {self.spawn_error}", file=sys.stderr, flush=True)

        window.connect("map", self._on_mapped)
        window.present()

    def _on_child_exited(self, _terminal: Vte.Terminal, _status: int) -> None:
        if not self.e2e:
            self.quit()

    def _on_mapped(self, _window: Gtk.Window) -> None:
        self.window_mapped = True
        if self.e2e:
            GLib.timeout_add(500, self._write_evidence_when_ready)

    def _write_evidence_when_ready(self) -> bool:
        if self.evidence_written or not self.evidence_path:
            return False
        path = pathlib.Path(self.evidence_path)
        runtime_text = os.environ.get("XDG_RUNTIME_DIR", "")
        if not runtime_text or path.parent.resolve() != pathlib.Path(runtime_text).resolve():
            raise RuntimeError("refusing SWIR Terminal evidence path outside XDG_RUNTIME_DIR")
        assert self.terminal is not None
        pty_attached = self.terminal.get_pty() is not None
        payload = {
            "schema": EVIDENCE_SCHEMA,
            "passed": self.window_mapped and self.spawn_requested and pty_attached and not self.spawn_error,
            "applicationId": APP_ID,
            "nativeToolkit": "gtk4-vte",
            "displayProtocol": "wayland",
            "windowMapped": self.window_mapped,
            "ptyAttached": pty_attached,
            "loginShell": self.shell_path,
            "privilegedOperations": False,
            "shellCommandInterpolation": False,
            "scrollbackLines": 10000,
            "spawnApi": self.spawn_api,
            "spawnError": self.spawn_error,
            "vteRuntimeVersion": f"{Vte.get_major_version()}.{Vte.get_minor_version()}.{Vte.get_micro_version()}",
        }
        path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
        path.chmod(0o600)
        self.evidence_written = True
        GLib.timeout_add(200, self._finish_e2e)
        return False

    def _finish_e2e(self) -> bool:
        self.quit()
        return False


if __name__ == "__main__":
    raise SystemExit(SwirTerminal().run(sys.argv))
