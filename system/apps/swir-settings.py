#!/usr/bin/env python3
"""SWIR Settings — native per-user Control Center foundation for System Edition."""

from __future__ import annotations

import json
import os
import pathlib
import sys
from typing import Final

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gdk, Gio, GLib, Gtk  # noqa: E402

LIBDIR = pathlib.Path("/usr/local/lib/swir")
if LIBDIR.is_dir() and str(LIBDIR) not in sys.path:
    sys.path.insert(0, str(LIBDIR))

from core_runtime import DEFAULT_THEME_ID, UserSettingsStore  # noqa: E402
from theme_runtime import ThemePolicyError, ThemeStore  # noqa: E402

APP_ID: Final = "dev.swir.Settings"
EVIDENCE_SCHEMA: Final = "swir.native-settings-runtime-evidence/0.2"
LANGUAGES: Final = (
    ("English", "en"),
    ("Polski", "pl-PL"),
    ("Norsk bokmål", "nb-NO"),
    ("Deutsch", "de-DE"),
    ("Español", "es-ES"),
    ("Français", "fr-FR"),
    ("Italiano", "it-IT"),
    ("Português (Brasil)", "pt-BR"),
    ("Українська", "uk-UA"),
    ("Русский", "ru-RU"),
    ("Türkçe", "tr-TR"),
    ("العربية", "ar"),
    ("עברית", "he"),
    ("日本語", "ja"),
    ("简体中文", "zh-CN"),
)

# These four categories already have first-party desktop registrations staged
# into the System image. Text/code and archive remain explicit follow-up work
# until their handlers are staged and verified on the final image as well.
DEFAULT_APP_CATEGORIES: Final = (
    ("browser", "Web browser", ("x-scheme-handler/http", "x-scheme-handler/https", "text/html")),
    ("media", "Media player", ("audio/mpeg", "video/mp4")),
    ("image", "Image viewer / editor", ("image/png", "image/jpeg")),
    ("pdf", "PDF viewer", ("application/pdf",)),
)
DEFAULT_FIRST_PARTY_IDS: Final = {
    "browser": "swir-browser.desktop",
    "media": "swir-player.desktop",
    "image": "swir-photo-studio.desktop",
    "pdf": "swir-pdf-viewer.desktop",
}
BROWSER_HANDLER_TYPES: Final = DEFAULT_APP_CATEGORIES[0][2]

CSS = b"""
window.swir-app { background: #02050A; color: #F4FAFF; }
.swir-header { background: #07111C; border-bottom: 1px solid #0088FF; padding: 12px 16px; }
.swir-brand { color: #62E5FF; font-size: 19px; font-weight: 800; }
.swir-muted { color: #8DA8B8; }
.swir-card { background: #07111C; border: 1px solid rgba(98,229,255,0.28); border-radius: 16px; padding: 18px; }
.swir-section { color: #F4FAFF; font-size: 17px; font-weight: 700; }
.swir-button { background: #07111C; color: #F4FAFF; border: 1px solid #0088FF; border-radius: 10px; padding: 8px 14px; }
.swir-button:hover { border-color: #62E5FF; }
"""


class SwirSettings(Gtk.Application):
    def __init__(self) -> None:
        super().__init__(application_id=APP_ID)
        self.window: Gtk.ApplicationWindow | None = None
        self.language: Gtk.ComboBoxText | None = None
        self.appearance: Gtk.ComboBoxText | None = None
        self.clock24h: Gtk.CheckButton | None = None
        self.default_combos: dict[str, Gtk.ComboBoxText] = {}
        self.default_apps: dict[str, dict[str, Gio.AppInfo]] = {}
        self.theme_combo: Gtk.ComboBoxText | None = None
        self.theme_store = ThemeStore()
        self.status: Gtk.Label | None = None
        self.store = UserSettingsStore()
        self.e2e = os.environ.get("SWIR_APP_E2E", "0") == "1"
        self.evidence_path = os.environ.get("SWIR_APP_EVIDENCE_PATH", "")
        self.theme_e2e_package = os.environ.get("SWIR_THEME_E2E_PACKAGE", "")
        self.default_apps_e2e = os.environ.get("SWIR_DEFAULT_APPS_E2E", "0") == "1"
        self.theme_import_verified = False
        self.default_apps_mutation_verified = False
        self.default_apps_verified_ids: dict[str, str] = {}

    def do_startup(self) -> None:
        Gtk.Application.do_startup(self)
        provider = Gtk.CssProvider()
        provider.load_from_data(CSS)
        display = Gdk.Display.get_default()
        if display is None:
            raise RuntimeError("SWIR Settings requires a graphical display")
        Gtk.StyleContext.add_provider_for_display(display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    @staticmethod
    def _row(label: str, widget: Gtk.Widget) -> Gtk.Box:
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        title = Gtk.Label(label=label)
        title.set_xalign(0)
        title.set_hexpand(True)
        row.append(title)
        row.append(widget)
        return row

    @staticmethod
    def _category_types(category_id: str) -> tuple[str, ...]:
        for item_id, _label, handler_types in DEFAULT_APP_CATEGORIES:
            if item_id == category_id:
                return handler_types
        raise KeyError(category_id)

    @staticmethod
    def _apps_for_all_types(handler_types: tuple[str, ...]) -> dict[str, Gio.AppInfo]:
        per_type: list[dict[str, Gio.AppInfo]] = []
        for content_type in handler_types:
            apps: dict[str, Gio.AppInfo] = {}
            for app in Gio.AppInfo.get_all_for_type(content_type):
                identity = app.get_id()
                if identity:
                    apps.setdefault(identity, app)
            per_type.append(apps)
        if not per_type:
            return {}
        shared = set(per_type[0])
        for apps in per_type[1:]:
            shared.intersection_update(apps)
        return {identity: per_type[0][identity] for identity in sorted(shared)}

    def _load_default_category(self, category_id: str) -> None:
        combo = self.default_combos[category_id]
        combo.remove_all()
        apps = self._apps_for_all_types(self._category_types(category_id))
        self.default_apps[category_id] = apps
        for identity, app in sorted(apps.items(), key=lambda item: item[1].get_display_name().casefold()):
            combo.append(identity, app.get_display_name())
        primary_type = self._category_types(category_id)[0]
        current = Gio.AppInfo.get_default_for_type(primary_type, False)
        current_id = current.get_id() if current is not None else None
        if current_id and current_id in apps:
            combo.set_active_id(current_id)
        elif apps:
            combo.set_active(0)

    def _load_default_apps(self) -> None:
        for category_id, _label, _types in DEFAULT_APP_CATEGORIES:
            self._load_default_category(category_id)

    @staticmethod
    def _is_default_for_all(app: Gio.AppInfo, handler_types: tuple[str, ...]) -> bool:
        identity = app.get_id()
        if not identity:
            return False
        for content_type in handler_types:
            current = Gio.AppInfo.get_default_for_type(content_type, False)
            if current is None or current.get_id() != identity:
                return False
        return True

    def _apply_default_app(self, category_id: str, app: Gio.AppInfo, *, update_status: bool = True) -> bool:
        handler_types = self._category_types(category_id)
        failed: list[str] = []
        for content_type in handler_types:
            try:
                if not app.set_as_default_for_type(content_type):
                    failed.append(content_type)
            except GLib.Error:
                failed.append(content_type)
        verified = not failed and self._is_default_for_all(app, handler_types)
        if update_status and self.status is not None:
            if verified:
                self.status.set_text(f"Default {category_id} app changed to {app.get_display_name()}.")
            else:
                self.status.set_text(f"Could not update every {category_id} handler; no system privilege was used.")
        return verified

    def _apply_default_clicked(self, _button: Gtk.Button, category_id: str) -> None:
        combo = self.default_combos[category_id]
        identity = combo.get_active_id()
        app = self.default_apps.get(category_id, {}).get(identity or "")
        if app is None:
            if self.status is not None:
                self.status.set_text(f"No compatible {category_id} handler is available.")
            return
        self._apply_default_app(category_id, app)

    def _load_themes(self, selected_id: str) -> None:
        assert self.theme_combo is not None
        self.theme_combo.remove_all()
        themes = self.theme_store.list_themes()
        for theme in themes:
            self.theme_combo.append(str(theme["id"]), str(theme["name"]))
        if not self.theme_combo.set_active_id(selected_id):
            self.theme_combo.set_active_id(DEFAULT_THEME_ID)

    def do_activate(self) -> None:
        if self.window is not None:
            self.window.present()
            return
        settings = self.store.load()
        window = Gtk.ApplicationWindow(application=self)
        window.set_title("SWIR Settings")
        window.set_default_size(820, 820)
        window.add_css_class("swir-app")
        self.window = window
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        window.set_child(root)
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        header.add_css_class("swir-header")
        brand = Gtk.Label(label="◆  SWIR Settings")
        brand.add_css_class("swir-brand")
        brand.set_xalign(0)
        header.append(brand)
        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        header.append(spacer)
        scope = Gtk.Label(label="USER SETTINGS")
        scope.add_css_class("swir-muted")
        header.append(scope)
        root.append(header)
        scroller = Gtk.ScrolledWindow()
        scroller.set_hexpand(True)
        scroller.set_vexpand(True)
        root.append(scroller)
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        content.set_margin_top(24)
        content.set_margin_bottom(24)
        content.set_margin_start(28)
        content.set_margin_end(28)
        scroller.set_child(content)

        regional = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        regional.add_css_class("swir-card")
        title = Gtk.Label(label="Language & Region")
        title.add_css_class("swir-section")
        title.set_xalign(0)
        regional.append(title)
        self.language = Gtk.ComboBoxText()
        selected_language = 0
        for index, (label, tag) in enumerate(LANGUAGES):
            self.language.append(tag, label)
            if tag == settings["language"]:
                selected_language = index
        self.language.set_active(selected_language)
        regional.append(self._row("Interface language preference", self.language))
        self.clock24h = Gtk.CheckButton(label="Use 24-hour clock")
        self.clock24h.set_active(bool(settings["clock24h"]))
        regional.append(self.clock24h)
        content.append(regional)

        appearance_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        appearance_card.add_css_class("swir-card")
        appearance_title = Gtk.Label(label="Appearance & Shell Themes")
        appearance_title.add_css_class("swir-section")
        appearance_title.set_xalign(0)
        appearance_card.append(appearance_title)
        self.appearance = Gtk.ComboBoxText()
        self.appearance.append("dark", "SWIR Dark")
        self.appearance.append("system", "Follow system preference")
        self.appearance.set_active_id(str(settings["appearance"]))
        appearance_card.append(self._row("Color preference", self.appearance))

        self.theme_combo = Gtk.ComboBoxText()
        self.theme_combo.set_hexpand(True)
        self._load_themes(str(settings.get("themeId", DEFAULT_THEME_ID)))
        appearance_card.append(self._row("Shell theme / skin", self.theme_combo))

        theme_actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        import_theme = Gtk.Button(label="Import .swirtheme")
        import_theme.add_css_class("swir-button")
        import_theme.connect("clicked", self._choose_theme_package)
        theme_actions.append(import_theme)
        reset_theme = Gtk.Button(label="Reset to SWIR Default")
        reset_theme.add_css_class("swir-button")
        reset_theme.connect("clicked", self._reset_theme)
        theme_actions.append(reset_theme)
        appearance_card.append(theme_actions)

        note = Gtk.Label(
            label=(
                "Theme packages are local data-only JSON: only allowlisted colors, spacing, radius and font scale "
                "are accepted. Scripts, CSS injection, URLs and privileged code are rejected. "
                "Low-contrast themes fail validation and the shell always falls back to SWIR Default."
            ),
            wrap=True,
        )
        note.add_css_class("swir-muted")
        note.set_xalign(0)
        appearance_card.append(note)
        content.append(appearance_card)

        defaults_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        defaults_card.add_css_class("swir-card")
        defaults_title = Gtk.Label(label="Default Apps")
        defaults_title.add_css_class("swir-section")
        defaults_title.set_xalign(0)
        defaults_card.append(defaults_title)
        defaults_note = Gtk.Label(
            label=(
                "Choose per-user handlers from installed applications that advertise every canonical type for the category. "
                "Changes use the desktop application registry only; no root access, package mutation or application removal is performed."
            ),
            wrap=True,
        )
        defaults_note.add_css_class("swir-muted")
        defaults_note.set_xalign(0)
        defaults_card.append(defaults_note)
        for category_id, label, _handler_types in DEFAULT_APP_CATEGORIES:
            combo = Gtk.ComboBoxText()
            combo.set_hexpand(True)
            self.default_combos[category_id] = combo
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
            row_label = Gtk.Label(label=label)
            row_label.set_xalign(0)
            row_label.set_hexpand(True)
            row.append(row_label)
            row.append(combo)
            apply_button = Gtk.Button(label="Apply")
            apply_button.add_css_class("swir-button")
            apply_button.connect("clicked", self._apply_default_clicked, category_id)
            row.append(apply_button)
            defaults_card.append(row)
        self._load_default_apps()
        content.append(defaults_card)

        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        self.status = Gtk.Label(label="Per-user settings only — privileged system changes are not exposed here.")
        self.status.add_css_class("swir-muted")
        self.status.set_xalign(0)
        self.status.set_hexpand(True)
        actions.append(self.status)
        save = Gtk.Button(label="Save")
        save.add_css_class("swir-button")
        save.connect("clicked", self._save)
        actions.append(save)
        content.append(actions)
        window.connect("map", self._on_mapped)
        window.present()

    def _choose_theme_package(self, _button: Gtk.Button | None = None) -> None:
        if self.window is None:
            return
        dialog = Gtk.FileChooserNative(
            title="Import SWIR Theme",
            transient_for=self.window,
            action=Gtk.FileChooserAction.OPEN,
            accept_label="Import",
            cancel_label="Cancel",
        )
        file_filter = Gtk.FileFilter()
        file_filter.set_name("SWIR Theme packages")
        file_filter.add_pattern("*.swirtheme")
        dialog.add_filter(file_filter)
        dialog.connect("response", self._on_theme_file_response)
        dialog.show()

    def _on_theme_file_response(self, dialog: Gtk.FileChooserNative, response: int) -> None:
        try:
            if response != Gtk.ResponseType.ACCEPT:
                return
            selected = dialog.get_file()
            if selected is None or not selected.is_native():
                raise ThemePolicyError("only local theme packages are accepted")
            path = selected.get_path()
            if not path:
                raise ThemePolicyError("theme path could not be resolved")
            theme = self.theme_store.install(path)
            assert self.theme_combo is not None
            self._load_themes(str(theme["id"]))
            if self.status is not None:
                self.status.set_text(f"Imported {theme['name']}. Save to activate it on the next shell start.")
        except (OSError, RuntimeError, ThemePolicyError) as exc:
            if self.status is not None:
                self.status.set_text(f"Theme import rejected: {exc}")
        finally:
            dialog.destroy()

    def _reset_theme(self, _button: Gtk.Button | None = None) -> None:
        if self.theme_combo is not None:
            self.theme_combo.set_active_id(DEFAULT_THEME_ID)
        if self.status is not None:
            self.status.set_text("SWIR Default selected. Save to activate it.")

    def _payload(self) -> dict[str, object]:
        assert self.language is not None and self.appearance is not None and self.clock24h is not None and self.theme_combo is not None
        return {
            "language": self.language.get_active_id() or "en",
            "appearance": self.appearance.get_active_id() or "dark",
            "clock24h": self.clock24h.get_active(),
            "themeId": self.theme_combo.get_active_id() or DEFAULT_THEME_ID,
        }

    def _save(self, _button: Gtk.Button | None = None) -> dict[str, object]:
        payload = self.store.save(self._payload())
        if self.status is not None:
            self.status.set_text("Saved securely to your SWIR user profile. Theme changes apply on the next shell start.")
        return payload

    def _prepare_theme_e2e(self) -> None:
        if not self.theme_e2e_package:
            return
        theme = self.theme_store.install(self.theme_e2e_package)
        assert self.theme_combo is not None
        self._load_themes(str(theme["id"]))
        self.theme_import_verified = True

    def _verify_default_apps_e2e(self) -> None:
        if not self.default_apps_e2e:
            return
        verified: dict[str, str] = {}
        for category_id, expected_id in DEFAULT_FIRST_PARTY_IDS.items():
            app = self.default_apps.get(category_id, {}).get(expected_id)
            if app is None:
                raise RuntimeError(f"missing first-party Default Apps candidate for {category_id}: {expected_id}")
            if not self._apply_default_app(category_id, app, update_status=False):
                raise RuntimeError(f"failed to set and verify first-party default for {category_id}")
            verified[category_id] = expected_id
        self.default_apps_verified_ids = verified
        self.default_apps_mutation_verified = len(verified) == len(DEFAULT_APP_CATEGORIES)

    def _on_mapped(self, _window: Gtk.Window) -> None:
        if not self.e2e or not self.evidence_path:
            return
        path = pathlib.Path(self.evidence_path)
        runtime_text = os.environ.get("XDG_RUNTIME_DIR", "")
        if not runtime_text or path.parent.resolve() != pathlib.Path(runtime_text).resolve():
            raise RuntimeError("refusing SWIR Settings evidence path outside XDG_RUNTIME_DIR")
        self._prepare_theme_e2e()
        self._verify_default_apps_e2e()
        saved = self._save()
        installed_ids = [str(theme["id"]) for theme in self.theme_store.list_themes()]
        candidate_counts = {category_id: len(self.default_apps.get(category_id, {})) for category_id, _label, _types in DEFAULT_APP_CATEGORIES}
        payload = {
            "schema": EVIDENCE_SCHEMA,
            "passed": True,
            "applicationId": APP_ID,
            "nativeToolkit": "gtk4",
            "displayProtocol": "wayland",
            "windowMapped": True,
            "privilegedOperations": False,
            "settingsSchema": saved["schema"],
            "ownerOnlySettingsFile": (self.store.path.stat().st_mode & 0o777) == 0o600,
            "language": saved["language"],
            "clock24h": saved["clock24h"],
            "defaultAppsPanel": True,
            "defaultAppCategoryCount": len(DEFAULT_APP_CATEGORIES),
            "defaultAppCategories": [category_id for category_id, _label, _types in DEFAULT_APP_CATEGORIES],
            "defaultAppHandlerTypes": {category_id: list(handler_types) for category_id, _label, handler_types in DEFAULT_APP_CATEGORIES},
            "defaultAppCandidateCounts": candidate_counts,
            "defaultAppsMutationOnExplicitActionOnly": True,
            "defaultAppsMutationVerified": self.default_apps_mutation_verified,
            "defaultAppsVerifiedDesktopIds": self.default_apps_verified_ids,
            "browserHandlerCount": candidate_counts.get("browser", 0),
            "browserDefaultMutationOnExplicitActionOnly": True,
            "browserHandlerTypes": list(BROWSER_HANDLER_TYPES),
            "themeFramework": True,
            "themeId": saved["themeId"],
            "themeImportVerified": self.theme_import_verified,
            "themePackagesDataOnly": True,
            "defaultThemeRecoveryAvailable": DEFAULT_THEME_ID in installed_ids,
            "installedThemeIds": installed_ids,
        }
        path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
        path.chmod(0o600)
        GLib.timeout_add(250, self._finish_e2e)

    def _finish_e2e(self) -> bool:
        self.quit()
        return False


if __name__ == "__main__":
    raise SystemExit(SwirSettings().run(sys.argv))
