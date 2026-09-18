#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import pathlib
import stat
import tempfile

from core_runtime import (
    DEFAULT_THEME_ID,
    SETTINGS_SCHEMA,
    THEME_SCHEMA,
    ThemePolicyError,
    ThemeStore,
    UserSettingsStore,
    contrast_ratio,
    list_directory,
    resolve_directory,
    theme_css,
    validate_settings,
    validate_theme,
)


def expect_error(callable_obj, expected: type[BaseException]) -> None:
    try:
        callable_obj()
    except expected:
        return
    raise AssertionError(f"expected {expected.__name__}")


def sample_theme() -> dict[str, object]:
    return {
        "schema": THEME_SCHEMA,
        "id": "swir.midnight",
        "name": "Midnight",
        "tokens": {
            "background": "#000000",
            "surface": "#101820",
            "primary": "#0088FF",
            "accent": "#62E5FF",
            "text": "#FFFFFF",
            "muted": "#A7C2D2",
            "border": "#31566A",
            "radius": 10,
            "spacing": 12,
            "fontScale": 1.05,
        },
    }


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="swir-core-runtime-") as tmp:
        root = pathlib.Path(tmp)
        home = root / "home"
        home.mkdir()
        (home / "Folder").mkdir()
        (home / "visible.txt").write_text("hello", encoding="utf-8")
        (home / ".hidden.txt").write_text("hidden", encoding="utf-8")
        os.symlink(home / "Folder", home / "folder-link")

        assert resolve_directory(home) == home.resolve()
        expect_error(lambda: resolve_directory(home / "visible.txt"), NotADirectoryError)

        rows = list_directory(home)
        assert [row.name for row in rows] == ["Folder", "folder-link", "visible.txt"]
        assert rows[0].kind == "directory"
        assert rows[1].kind == "symlink"
        assert rows[2].kind == "file" and rows[2].size == 5
        assert ".hidden.txt" not in [row.name for row in rows]
        assert ".hidden.txt" in [row.name for row in list_directory(home, include_hidden=True)]

        store = UserSettingsStore(root / "config")
        defaults = store.load()
        assert defaults["schema"] == SETTINGS_SCHEMA
        assert defaults["themeId"] == DEFAULT_THEME_ID
        saved = store.save({
            "appearance": "system",
            "language": "pl-PL",
            "clock24h": False,
            "themeId": "swir.midnight",
        })
        assert saved == {
            "schema": SETTINGS_SCHEMA,
            "appearance": "system",
            "language": "pl-PL",
            "clock24h": False,
            "themeId": "swir.midnight",
        }
        assert store.load() == saved
        assert stat.S_IMODE(store.path.stat().st_mode) == 0o600
        assert stat.S_IMODE(store.directory.stat().st_mode) == 0o700

        expect_error(lambda: validate_settings({"appearance": "neon-random"}), ValueError)
        expect_error(lambda: validate_settings({"language": "../../bad"}), ValueError)
        expect_error(lambda: validate_settings({"clock24h": "yes"}), ValueError)
        expect_error(lambda: validate_settings({"themeId": "../../bad"}), ValueError)

        legacy = validate_settings({"appearance": "dark", "language": "en", "clock24h": True})
        assert legacy["themeId"] == DEFAULT_THEME_ID

        custom = sample_theme()
        validated = validate_theme(custom)
        assert validated["id"] == "swir.midnight"
        assert contrast_ratio("#FFFFFF", "#000000") > 4.5
        css = theme_css(validated)
        assert b"window.swir-shell" in css and b"#62E5FF" in css
        assert b"url(" not in css and b"@import" not in css

        theme_source = root / "midnight.swirtheme"
        theme_source.write_text(json.dumps(custom), encoding="utf-8")
        theme_store = ThemeStore(root / "data")
        installed = theme_store.install(theme_source)
        assert installed["id"] == "swir.midnight"
        loaded, fallback = theme_store.load("swir.midnight")
        assert loaded["id"] == "swir.midnight" and fallback is False
        recovered, fallback = theme_store.load("missing.theme")
        assert recovered["id"] == DEFAULT_THEME_ID and fallback is True
        installed_path = theme_store.directory / "swir.midnight.swirtheme"
        assert stat.S_IMODE(installed_path.stat().st_mode) == 0o600
        assert stat.S_IMODE(theme_store.directory.stat().st_mode) == 0o700

        unsafe = sample_theme()
        unsafe["script"] = "rm -rf /"
        expect_error(lambda: validate_theme(unsafe), ThemePolicyError)
        traversal = sample_theme()
        traversal["id"] = "../../escape"
        expect_error(lambda: validate_theme(traversal), ThemePolicyError)
        css_injection = sample_theme()
        css_injection["tokens"] = {**sample_theme()["tokens"], "accent": "url(https://example.invalid)"}
        expect_error(lambda: validate_theme(css_injection), ThemePolicyError)
        low_contrast = sample_theme()
        low_contrast["tokens"] = {**sample_theme()["tokens"], "text": "#111111"}
        expect_error(lambda: validate_theme(low_contrast), ThemePolicyError)
        os.symlink(theme_source, root / "linked.swirtheme")
        expect_error(lambda: theme_store.install(root / "linked.swirtheme"), ThemePolicyError)

        store.path.write_text(json.dumps({"schema": "future/9"}), encoding="utf-8")
        expect_error(store.load, ValueError)
        store.path.unlink()
        os.symlink(root / "outside.json", store.path)
        expect_error(store.load, RuntimeError)

    print("native core runtime self-test: PASS")


if __name__ == "__main__":
    main()
