#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import stat
import tempfile
import zipfile
from unittest import mock

from backup_runtime import BackupError, BackupRuntime, RootSpec, SCHEMA, self_test


def expect_backup_error(fn) -> None:
    try:
        fn()
    except BackupError:
        return
    raise AssertionError("expected BackupError")


def write_archive(path: pathlib.Path, manifest: dict, members: list[tuple[zipfile.ZipInfo | str, bytes]]) -> None:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(manifest, separators=(",", ":")))
        for name, payload in members:
            archive.writestr(name, payload)
    os.chmod(path, 0o600)


def main() -> None:
    baseline = self_test()
    assert baseline["restoreVerified"] is True

    with tempfile.TemporaryDirectory(prefix="swir-backup-hostile-") as temp:
        base = pathlib.Path(temp)
        config = base / "config" / "swir"
        data = base / "data" / "swir"
        out = base / "out"
        config.mkdir(parents=True, mode=0o700)
        data.mkdir(parents=True, mode=0o700)
        out.mkdir(mode=0o700)
        (config / "settings.json").write_text("original-config\n", encoding="utf-8")
        (data / "notes.txt").write_text("original-data\n", encoding="utf-8")
        runtime = BackupRuntime((RootSpec("config", config), RootSpec("data", data)))

        expect_backup_error(lambda: runtime.create_backup(data))

        traversal = out / "traversal.zip"
        payload = b"bad"
        manifest = {
            "schema": SCHEMA,
            "createdAt": "2026-09-18T00:00:00Z",
            "roots": ["config", "data"],
            "entries": [{
                "root": "config",
                "path": "../escape",
                "size": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }],
        }
        write_archive(traversal, manifest, [("payload/config/../escape", payload)])
        expect_backup_error(lambda: runtime.inspect_backup(traversal))

        unmanifested = out / "unmanifested.zip"
        manifest["entries"] = []
        write_archive(unmanifested, manifest, [("payload/config/extra", b"extra")])
        expect_backup_error(lambda: runtime.inspect_backup(unmanifested))

        symlink_archive = out / "symlink.zip"
        symlink_info = zipfile.ZipInfo("payload/config/link")
        symlink_info.external_attr = (stat.S_IFLNK | 0o777) << 16
        manifest["entries"] = [{
            "root": "config",
            "path": "link",
            "size": 6,
            "sha256": hashlib.sha256(b"target").hexdigest(),
        }]
        write_archive(symlink_archive, manifest, [(symlink_info, b"target")])
        expect_backup_error(lambda: runtime.inspect_backup(symlink_archive))

        backup = runtime.create_backup(out)
        (config / "settings.json").write_text("changed-config\n", encoding="utf-8")
        (data / "notes.txt").write_text("changed-data\n", encoding="utf-8")
        real_rename = os.rename

        def flaky_rename(src, dst, *args, **kwargs):
            src_path = pathlib.Path(src)
            if src_path.name.startswith(".swir-restore-") and src_path.name.endswith("-data"):
                raise OSError("injected second-root commit failure")
            return real_rename(src, dst, *args, **kwargs)

        with mock.patch("backup_runtime.os.rename", side_effect=flaky_rename):
            try:
                runtime.restore_backup(backup.path)
            except OSError as exc:
                assert "injected" in str(exc)
            else:
                raise AssertionError("restore failure injection was not exercised")

        assert (config / "settings.json").read_text(encoding="utf-8") == "changed-config\n"
        assert (data / "notes.txt").read_text(encoding="utf-8") == "changed-data\n"

    print("SWIR backup hostile-input and rollback self-test: OK")


if __name__ == "__main__":
    main()
