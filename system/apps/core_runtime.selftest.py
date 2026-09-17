#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import pathlib
import tempfile

from core_runtime import SETTINGS_SCHEMA, UserSettingsStore, list_directory, resolve_directory, validate_settings


def expect_error(callable_obj, expected: type[BaseException]) -> None:
    try:
        callable_obj()
    except expected:
        return
    raise AssertionError(f"expected {expected.__name__}")


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
        assert store.load()["schema"] == SETTINGS_SCHEMA
        saved = store.save({"appearance": "system", "language": "pl-PL", "clock24h": False})
        assert saved == {
            "schema": SETTINGS_SCHEMA,
            "appearance": "system",
            "language": "pl-PL",
            "clock24h": False,
        }
        assert store.load() == saved
        assert (store.path.stat().st_mode & 0o777) == 0o600
        assert (store.directory.stat().st_mode & 0o777) == 0o700

        expect_error(lambda: validate_settings({"appearance": "neon-random"}), ValueError)
        expect_error(lambda: validate_settings({"language": "../../bad"}), ValueError)
        expect_error(lambda: validate_settings({"clock24h": "yes"}), ValueError)

        store.path.write_text(json.dumps({"schema": "future/9"}), encoding="utf-8")
        expect_error(store.load, ValueError)
        store.path.unlink()
        os.symlink(root / "outside.json", store.path)
        expect_error(store.load, RuntimeError)

    print("native core runtime self-test: PASS")


if __name__ == "__main__":
    main()
