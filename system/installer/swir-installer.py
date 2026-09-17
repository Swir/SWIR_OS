#!/usr/bin/env python3
"""Native GTK4 installer UI for SWIR OS System Edition Live media."""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import subprocess
import sys
from dataclasses import dataclass
from typing import Any

ENGINE = pathlib.Path("/usr/local/sbin/swir-install-engine")
HELPER = pathlib.Path("/usr/local/libexec/swir-installer-helper")
LIVE_MARKER = pathlib.Path("/var/lib/swir/live/live.json")
USERNAME_RE = re.compile(r"^[a-z_][a-z0-9_-]{0,30}$")
LOCALES = ["en_US.UTF-8", "pl_PL.UTF-8", "nb_NO.UTF-8", "de_DE.UTF-8", "es_ES.UTF-8", "fr_FR.UTF-8"]
KEYBOARDS = ["us", "pl", "no", "de", "es", "fr"]
TIMEZONES = ["Etc/UTC", "Europe/Oslo", "Europe/Warsaw", "Europe/Berlin", "Europe/London", "America/New_York"]


@dataclass(frozen=True)
class TargetDisk:
    stable_path: str
    device: str
    size: int
    model: str
    serial: str

    @property
    def label(self) -> str:
        gib = self.size / (1024 ** 3)
        ident = self.model or self.serial or pathlib.Path(self.stable_path).name
        return f"{ident} — {gib:.1f} GiB ({self.stable_path})"


def run_json(args: list[str], *, input_text: str | None = None) -> dict[str, Any]:
    proc = subprocess.run(args, input=input_text, text=True, capture_output=True, check=True)
    value = json.loads(proc.stdout)
    if not isinstance(value, dict):
        raise RuntimeError("command did not return a JSON object")
    return value


def enumerate_targets() -> list[TargetDisk]:
    by_id = pathlib.Path("/dev/disk/by-id")
    if not by_id.is_dir():
        return []
    seen: set[str] = set()
    targets: list[TargetDisk] = []
    for entry in sorted(by_id.iterdir(), key=lambda p: p.name):
        if "-part" in entry.name or not entry.is_symlink():
            continue
        try:
            real = os.path.realpath(entry)
            if real in seen:
                continue
            info = run_json(["lsblk", "-J", "-b", "-d", "-o", "PATH,TYPE,SIZE,RO,MODEL,SERIAL", real])
            devices = info.get("blockdevices") or []
            if len(devices) != 1:
                continue
            d = devices[0]
            if d.get("type") != "disk" or int(d.get("ro") or 0) != 0:
                continue
            size = int(d.get("size") or 0)
            if size < 6 * 1024 ** 3:
                continue
            seen.add(real)
            targets.append(TargetDisk(str(entry), real, size, str(d.get("model") or "").strip(), str(d.get("serial") or "").strip()))
        except (OSError, ValueError, subprocess.CalledProcessError, json.JSONDecodeError):
            continue
    return targets


def validate_identity(username: str, password: str, password2: str, locale: str, keyboard: str, timezone: str) -> str | None:
    if not USERNAME_RE.fullmatch(username) or username == "root":
        return "Use a lowercase username (letters, digits, _ or -), not root."
    if len(password.encode("utf-8")) < 8:
        return "Password must be at least 8 bytes long."
    if password != password2:
        return "Passwords do not match."
    if locale not in LOCALES:
        return "Choose a supported installer locale."
    if keyboard not in KEYBOARDS:
        return "Choose a supported keyboard layout."
    if timezone not in TIMEZONES:
        return "Choose a supported time zone."
    return None


def self_test() -> None:
    assert validate_identity("swir", "abcdefgh", "abcdefgh", "en_US.UTF-8", "us", "Etc/UTC") is None
    assert validate_identity("Root User", "abcdefgh", "abcdefgh", "en_US.UTF-8", "us", "Etc/UTC")
    assert validate_identity("swir", "short", "short", "en_US.UTF-8", "us", "Etc/UTC")
    assert validate_identity("swir", "abcdefgh", "different", "en_US.UTF-8", "us", "Etc/UTC")
    print("SWIR graphical installer UI self-test OK")


def run_gui(*, smoke_window: bool = False, evidence_path: str | None = None) -> int:
    import gi
    gi.require_version("Gtk", "4.0")
    from gi.repository import GLib, Gtk

    class InstallerWindow(Gtk.ApplicationWindow):
        def __init__(self, app: Gtk.Application) -> None:
            super().__init__(application=app, title="Install SWIR OS")
            self.set_default_size(900, 650)
            self.set_resizable(True)
            self.targets: list[TargetDisk] = []
            self.preview: dict[str, Any] | None = None
            self.installing = False

            root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
            self.set_child(root)

            header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
            header.set_margin_top(22); header.set_margin_bottom(18); header.set_margin_start(28); header.set_margin_end(28)
            title = Gtk.Label(label="SWIR OS  •  SYSTEM EDITION")
            title.add_css_class("title-2")
            title.set_xalign(0)
            header.append(title)
            root.append(header)

            self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.SLIDE_LEFT_RIGHT, transition_duration=180)
            self.stack.set_vexpand(True)
            root.append(self.stack)

            self._build_welcome()
            self._build_target()
            self._build_identity()
            self._build_review()
            self._build_progress()
            self.stack.set_visible_child_name("welcome")

            css = Gtk.CssProvider()
            css.load_from_data(b"""
window { background: #02050a; color: #f4faff; }
.install-page { padding: 32px; }
.muted { color: #8da8b8; }
.warning { color: #ffcc66; }
.danger { color: #ff6b7a; }
.accent { color: #62e5ff; }
button.suggested-action { background: #0088ff; color: white; }
card { background: #07111c; border-radius: 14px; padding: 18px; }
""")
            Gtk.StyleContext.add_provider_for_display(self.get_display(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

            if smoke_window:
                GLib.timeout_add(900, self._smoke_done)

        def page(self, heading: str, text: str) -> Gtk.Box:
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
            box.add_css_class("install-page")
            h = Gtk.Label(label=heading); h.add_css_class("title-1"); h.set_xalign(0); h.set_wrap(True)
            p = Gtk.Label(label=text); p.add_css_class("muted"); p.set_xalign(0); p.set_wrap(True)
            box.append(h); box.append(p)
            return box

        def nav(self, back_cb, next_label: str, next_cb) -> Gtk.Box:
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
            row.set_halign(Gtk.Align.END); row.set_margin_top(18)
            if back_cb:
                back = Gtk.Button(label="Back"); back.connect("clicked", back_cb); row.append(back)
            nxt = Gtk.Button(label=next_label); nxt.add_css_class("suggested-action"); nxt.connect("clicked", next_cb); row.append(nxt)
            return row

        def _build_welcome(self) -> None:
            page = self.page("Try SWIR OS or install it", "You are running the Live environment. Installation is optional. Internal disks are not changed until you choose a target, review the exact plan and confirm the target-bound erase token.")
            live = Gtk.Label(label="LIVE MODE  •  UEFI AMD64 DEVELOPMENT BUILD"); live.add_css_class("accent"); live.set_xalign(0); page.append(live)
            warning = Gtk.Label(label="Installing erases the selected target disk. Formatting cannot be undone without a separate backup."); warning.add_css_class("warning"); warning.set_xalign(0); warning.set_wrap(True); page.append(warning)
            page.append(self.nav(None, "Start installer", lambda *_: self._open_target()))
            self.stack.add_named(page, "welcome")

        def _build_target(self) -> None:
            page = self.page("Choose the installation disk", "Only stable whole-disk identities are shown. The booted Live USB is rejected again by the privileged install engine before any write.")
            self.target_dropdown = Gtk.DropDown.new_from_strings(["Refresh to detect disks"])
            self.target_dropdown.set_hexpand(True); page.append(self.target_dropdown)
            refresh = Gtk.Button(label="Refresh disks"); refresh.connect("clicked", lambda *_: self._refresh_targets()); page.append(refresh)
            self.target_error = Gtk.Label(); self.target_error.add_css_class("danger"); self.target_error.set_xalign(0); self.target_error.set_wrap(True); page.append(self.target_error)
            page.append(self.nav(lambda *_: self.stack.set_visible_child_name("welcome"), "Review target", lambda *_: self._preview_target()))
            self.stack.add_named(page, "target")

        def _build_identity(self) -> None:
            page = self.page("Create your account and region", "These settings are written to the installed system only after the disk installation succeeds. The password is sent through stdin to the narrow privileged helper and is never written to installer evidence.")
            grid = Gtk.Grid(column_spacing=14, row_spacing=12)
            self.username = Gtk.Entry(placeholder_text="username")
            self.password = Gtk.PasswordEntry(); self.password.set_show_peek_icon(True)
            self.password2 = Gtk.PasswordEntry(); self.password2.set_show_peek_icon(True)
            self.locale = Gtk.DropDown.new_from_strings(LOCALES); self.locale.set_selected(0)
            self.keyboard = Gtk.DropDown.new_from_strings(KEYBOARDS); self.keyboard.set_selected(0)
            self.timezone = Gtk.DropDown.new_from_strings(TIMEZONES); self.timezone.set_selected(0)
            fields = [("Username", self.username), ("Password", self.password), ("Repeat password", self.password2), ("Language / locale", self.locale), ("Keyboard", self.keyboard), ("Time zone", self.timezone)]
            for row, (label, widget) in enumerate(fields):
                lab = Gtk.Label(label=label); lab.set_xalign(0); grid.attach(lab, 0, row, 1, 1); grid.attach(widget, 1, row, 1, 1)
            page.append(grid)
            self.identity_error = Gtk.Label(); self.identity_error.add_css_class("danger"); self.identity_error.set_xalign(0); self.identity_error.set_wrap(True); page.append(self.identity_error)
            page.append(self.nav(lambda *_: self.stack.set_visible_child_name("target"), "Continue", lambda *_: self._validate_identity()))
            self.stack.add_named(page, "identity")

        def _build_review(self) -> None:
            page = self.page("Final review", "Verify the exact target and partition plan. To unlock Install, type the target-bound erase token shown below. The helper re-runs preview immediately before mutation and rejects stale tokens.")
            self.review_text = Gtk.Label(); self.review_text.set_xalign(0); self.review_text.set_wrap(True); self.review_text.set_selectable(True); page.append(self.review_text)
            self.token_entry = Gtk.Entry(placeholder_text="ERASE-SWIR-xxxxxxxxxxxx"); page.append(self.token_entry)
            self.review_error = Gtk.Label(); self.review_error.add_css_class("danger"); self.review_error.set_xalign(0); self.review_error.set_wrap(True); page.append(self.review_error)
            page.append(self.nav(lambda *_: self.stack.set_visible_child_name("identity"), "Erase target and install", lambda *_: self._start_install()))
            self.stack.add_named(page, "review")

        def _build_progress(self) -> None:
            page = self.page("Installing SWIR OS", "Keep the computer powered on. The Live USB must stay connected until installation reports success.")
            self.spinner = Gtk.Spinner(); self.spinner.set_size_request(48, 48); page.append(self.spinner)
            self.progress_text = Gtk.Label(label="Preparing…"); self.progress_text.set_xalign(0); self.progress_text.set_wrap(True); page.append(self.progress_text)
            self.stack.add_named(page, "progress")

        def _open_target(self) -> None:
            if not LIVE_MARKER.is_file() and not smoke_window:
                self.target_error.set_text("Installer is available only from verified SWIR Live media.")
            self._refresh_targets()
            self.stack.set_visible_child_name("target")

        def _refresh_targets(self) -> None:
            self.targets = enumerate_targets()
            labels = [t.label for t in self.targets] or ["No eligible target disks detected"]
            self.target_dropdown.set_model(Gtk.StringList.new(labels)); self.target_dropdown.set_selected(0)
            self.target_error.set_text("" if self.targets else "No eligible ≥6 GiB stable whole-disk target was detected.")

        def _selected_target(self) -> TargetDisk | None:
            idx = self.target_dropdown.get_selected()
            return self.targets[idx] if self.targets and idx < len(self.targets) else None

        def _preview_target(self) -> None:
            target = self._selected_target()
            if not target:
                self.target_error.set_text("Choose an eligible target disk first."); return
            try:
                self.preview = run_json([str(ENGINE), "preview", "--target", target.stable_path])
            except Exception as exc:
                self.target_error.set_text(f"Preview failed safely: {exc}"); return
            if self.preview.get("destructiveWritePerformed") is not False or not self.preview.get("confirmationToken"):
                self.target_error.set_text("Install engine returned an invalid read-only preview."); return
            self.target_error.set_text("")
            self.stack.set_visible_child_name("identity")

        def _selected_string(self, dropdown: Gtk.DropDown, values: list[str]) -> str:
            idx = dropdown.get_selected(); return values[idx] if idx < len(values) else ""

        def _identity_config(self) -> dict[str, str]:
            return {
                "username": self.username.get_text(), "password": self.password.get_text(),
                "locale": self._selected_string(self.locale, LOCALES), "keyboard": self._selected_string(self.keyboard, KEYBOARDS),
                "timezone": self._selected_string(self.timezone, TIMEZONES),
            }

        def _validate_identity(self) -> None:
            cfg = self._identity_config()
            error = validate_identity(cfg["username"], cfg["password"], self.password2.get_text(), cfg["locale"], cfg["keyboard"], cfg["timezone"])
            if error:
                self.identity_error.set_text(error); return
            if not self.preview:
                self.identity_error.set_text("Target preview expired. Return to target selection."); return
            self.identity_error.set_text("")
            plan = self.preview.get("partitionPlan") or []
            model = self.preview.get("targetModel") or self.preview.get("targetStablePath")
            size = int(self.preview.get("targetSizeBytes") or 0) / (1024 ** 3)
            token = str(self.preview.get("confirmationToken") or "")
            parts = "\n".join(f"• {p.get('role')}: {p.get('filesystem')} — {p.get('sizeMiB', p.get('size'))}" for p in plan)
            self.review_text.set_text(f"TARGET TO ERASE:\n{model}\n{size:.1f} GiB\n{self.preview.get('targetStablePath')}\n\nPARTITION PLAN:\n{parts}\n\nCONFIRMATION TOKEN:\n{token}")
            self.token_entry.set_text("")
            self.stack.set_visible_child_name("review")

        def _start_install(self) -> None:
            if self.installing or not self.preview:
                return
            token = str(self.preview.get("confirmationToken") or "")
            if self.token_entry.get_text().strip() != token:
                self.review_error.set_text("Type the exact target-bound erase token before installation."); return
            cfg = self._identity_config()
            request = {**cfg, "targetStablePath": str(self.preview.get("targetStablePath")), "confirmationToken": token}
            self.review_error.set_text("")
            self.installing = True; self.stack.set_visible_child_name("progress"); self.spinner.start(); self.progress_text.set_text("Partitioning and copying the system…")

            def worker() -> None:
                try:
                    result = run_json(["pkexec", str(HELPER)], input_text=json.dumps(request))
                    GLib.idle_add(self._install_done, result, None)
                except Exception as exc:
                    GLib.idle_add(self._install_done, None, str(exc))
            import threading
            threading.Thread(target=worker, daemon=True).start()

        def _install_done(self, result: dict[str, Any] | None, error: str | None) -> bool:
            self.spinner.stop(); self.installing = False
            if error or not result or result.get("status") != "installed":
                self.progress_text.set_text("Installation stopped safely. " + (error or "Privileged helper returned an invalid result."))
                return False
            self.progress_text.set_text("SWIR OS was installed successfully. Shut down, remove the Live USB, then boot from the installed disk.")
            return False

        def _smoke_done(self) -> bool:
            if evidence_path:
                pathlib.Path(evidence_path).write_text(json.dumps({"schema": "swir.graphical-installer-ui-smoke/0.1", "gtkWindowCreated": True, "waylandDisplay": os.environ.get("WAYLAND_DISPLAY"), "liveMutationPerformed": False}, sort_keys=True) + "\n", encoding="utf-8")
            self.close()
            return False

    class InstallerApp(Gtk.Application):
        def __init__(self) -> None:
            super().__init__(application_id="dev.swir.Installer")
        def do_activate(self) -> None:
            window = self.props.active_window or InstallerWindow(self)
            window.present()

    app = InstallerApp()
    return int(app.run([]))


def main() -> int:
    parser = argparse.ArgumentParser(description="SWIR OS graphical Live installer")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--smoke-window", action="store_true")
    parser.add_argument("--evidence")
    args = parser.parse_args()
    if args.self_test:
        self_test(); return 0
    if not LIVE_MARKER.is_file() and not args.smoke_window:
        print("SWIR Installer can only run from verified Live media.", file=sys.stderr)
        return 2
    return run_gui(smoke_window=args.smoke_window, evidence_path=args.evidence)


if __name__ == "__main__":
    raise SystemExit(main())
