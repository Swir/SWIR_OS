#!/usr/bin/env python3
"""Safe per-user SWIR data backup/restore runtime.

This module is intentionally unprivileged. It snapshots only SWIR-owned user
state below XDG_CONFIG_HOME/swir and XDG_DATA_HOME/swir. Archives are verified
before restore and live roots are swapped only after a complete staging pass.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import pathlib
import secrets
import shutil
import stat
import tempfile
import zipfile
from dataclasses import dataclass
from typing import Final, Iterable

SCHEMA: Final = "swir.user-backup/0.1"
MANIFEST_NAME: Final = "manifest.json"
PAYLOAD_PREFIX: Final = "payload/"
MAX_FILES: Final = 10_000
MAX_SINGLE_FILE_BYTES: Final = 128 * 1024 * 1024
MAX_TOTAL_BYTES: Final = 2 * 1024 * 1024 * 1024
MAX_ARCHIVE_BYTES: Final = 3 * 1024 * 1024 * 1024
MAX_PATH_CHARS: Final = 512
CHUNK_SIZE: Final = 1024 * 1024


class BackupError(RuntimeError):
    pass


@dataclass(frozen=True)
class RootSpec:
    name: str
    path: pathlib.Path


@dataclass(frozen=True)
class BackupEntry:
    root: str
    relative_path: str
    size: int
    sha256: str

    @property
    def archive_name(self) -> str:
        return f"{PAYLOAD_PREFIX}{self.root}/{self.relative_path}"


@dataclass(frozen=True)
class BackupInfo:
    path: pathlib.Path
    created_at: str
    entries: tuple[BackupEntry, ...]
    total_bytes: int


def _mode(path: pathlib.Path) -> int:
    return stat.S_IMODE(path.stat(follow_symlinks=False).st_mode)


def _safe_component_path(text: str) -> pathlib.PurePosixPath:
    if not isinstance(text, str) or not text or len(text) > MAX_PATH_CHARS:
        raise BackupError("backup entry path is empty or too long")
    p = pathlib.PurePosixPath(text)
    if p.is_absolute() or any(part in {"", ".", ".."} for part in p.parts):
        raise BackupError("backup entry path is unsafe")
    if "\\" in text or "\x00" in text:
        raise BackupError("backup entry path contains unsupported characters")
    return p


def _ensure_real_dir(path: pathlib.Path, *, create: bool = False, mode: int = 0o700) -> pathlib.Path:
    if create and not path.exists():
        path.mkdir(parents=True, mode=mode)
    if path.is_symlink() or not path.is_dir():
        raise BackupError(f"directory is missing or unsafe: {path}")
    return path.resolve()


def _ensure_regular_file(path: pathlib.Path) -> pathlib.Path:
    if path.is_symlink() or not path.is_file():
        raise BackupError(f"file is missing or unsafe: {path}")
    return path.resolve()


def _sha256_stream(handle) -> tuple[str, int]:
    digest = hashlib.sha256()
    total = 0
    while True:
        chunk = handle.read(CHUNK_SIZE)
        if not chunk:
            break
        total += len(chunk)
        if total > MAX_SINGLE_FILE_BYTES:
            raise BackupError("file exceeds per-file backup size limit")
        digest.update(chunk)
    return digest.hexdigest(), total


def _default_roots() -> tuple[RootSpec, RootSpec]:
    home = pathlib.Path.home()
    config_home = pathlib.Path(os.environ.get("XDG_CONFIG_HOME", home / ".config")).expanduser()
    data_home = pathlib.Path(os.environ.get("XDG_DATA_HOME", home / ".local/share")).expanduser()
    return (
        RootSpec("config", config_home / "swir"),
        RootSpec("data", data_home / "swir"),
    )


class BackupRuntime:
    def __init__(self, roots: Iterable[RootSpec] | None = None) -> None:
        selected = tuple(roots or _default_roots())
        if not selected or len({root.name for root in selected}) != len(selected):
            raise BackupError("backup root names must be unique")
        for root in selected:
            if root.name not in {"config", "data"}:
                raise BackupError("unsupported backup root")
            if not root.path.is_absolute():
                raise BackupError("backup roots must be absolute")
        self.roots = selected

    def _collect_entries(self) -> tuple[BackupEntry, ...]:
        entries: list[BackupEntry] = []
        total_bytes = 0
        for root in self.roots:
            if not root.path.exists():
                continue
            if root.path.is_symlink() or not root.path.is_dir():
                raise BackupError(f"SWIR user root is unsafe: {root.path}")
            root_real = root.path.resolve()
            for dirpath, dirnames, filenames in os.walk(root_real, topdown=True, followlinks=False):
                current = pathlib.Path(dirpath)
                safe_dirs: list[str] = []
                for dirname in sorted(dirnames):
                    candidate = current / dirname
                    if candidate.is_symlink():
                        raise BackupError(f"symlinked directory is not backup-safe: {candidate}")
                    st = candidate.stat(follow_symlinks=False)
                    if not stat.S_ISDIR(st.st_mode):
                        raise BackupError(f"special directory entry is not backup-safe: {candidate}")
                    safe_dirs.append(dirname)
                dirnames[:] = safe_dirs
                for filename in sorted(filenames):
                    candidate = current / filename
                    if candidate.is_symlink():
                        raise BackupError(f"symlinked file is not backup-safe: {candidate}")
                    st = candidate.stat(follow_symlinks=False)
                    if not stat.S_ISREG(st.st_mode):
                        raise BackupError(f"special file is not backup-safe: {candidate}")
                    if st.st_size > MAX_SINGLE_FILE_BYTES:
                        raise BackupError(f"file exceeds per-file backup size limit: {candidate}")
                    relative = candidate.relative_to(root_real).as_posix()
                    _safe_component_path(relative)
                    with candidate.open("rb") as handle:
                        digest, observed = _sha256_stream(handle)
                    if observed != st.st_size:
                        raise BackupError(f"file changed while backup was being prepared: {candidate}")
                    total_bytes += observed
                    if total_bytes > MAX_TOTAL_BYTES:
                        raise BackupError("backup exceeds total data size limit")
                    entries.append(BackupEntry(root.name, relative, observed, digest))
                    if len(entries) > MAX_FILES:
                        raise BackupError("backup exceeds file-count limit")
        return tuple(entries)

    def create_backup(self, destination_dir: pathlib.Path) -> BackupInfo:
        destination = _ensure_real_dir(destination_dir, create=True)
        for root in self.roots:
            if root.path.exists():
                root_real = root.path.resolve()
                try:
                    destination.relative_to(root_real)
                except ValueError:
                    pass
                else:
                    raise BackupError("backup destination must be outside SWIR data roots")

        entries = self._collect_entries()
        created = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        total = sum(entry.size for entry in entries)
        manifest = {
            "schema": SCHEMA,
            "createdAt": created,
            "scope": "swir-user-state",
            "roots": [root.name for root in self.roots],
            "limits": {
                "maxFiles": MAX_FILES,
                "maxSingleFileBytes": MAX_SINGLE_FILE_BYTES,
                "maxTotalBytes": MAX_TOTAL_BYTES,
            },
            "entries": [
                {
                    "root": e.root,
                    "path": e.relative_path,
                    "size": e.size,
                    "sha256": e.sha256,
                }
                for e in entries
            ],
        }
        token = secrets.token_hex(8)
        stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        final_path = destination / f"SWIR-user-backup-{stamp}-{token}.zip"
        temp_path = destination / f".swir-backup-{token}.tmp"
        if final_path.exists() or temp_path.exists():
            raise BackupError("backup output collision")
        try:
            fd = os.open(temp_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            os.close(fd)
            with zipfile.ZipFile(temp_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
                archive.writestr(MANIFEST_NAME, json.dumps(manifest, sort_keys=True, separators=(",", ":")))
                root_map = {root.name: root.path.resolve() for root in self.roots if root.path.exists()}
                for entry in entries:
                    source = root_map[entry.root] / pathlib.PurePosixPath(entry.relative_path)
                    source = _ensure_regular_file(source)
                    with source.open("rb") as handle:
                        payload = handle.read(MAX_SINGLE_FILE_BYTES + 1)
                    if len(payload) != entry.size or hashlib.sha256(payload).hexdigest() != entry.sha256:
                        raise BackupError(f"file changed while backup was being written: {source}")
                    info = zipfile.ZipInfo(entry.archive_name)
                    info.compress_type = zipfile.ZIP_DEFLATED
                    info.external_attr = (stat.S_IFREG | 0o600) << 16
                    archive.writestr(info, payload)
            if temp_path.stat().st_size > MAX_ARCHIVE_BYTES:
                raise BackupError("backup archive exceeds archive size limit")
            with temp_path.open("rb") as handle:
                os.fsync(handle.fileno())
            os.chmod(temp_path, 0o600, follow_symlinks=False)
            if final_path.exists():
                raise BackupError("backup output already exists")
            os.rename(temp_path, final_path)
            dir_fd = os.open(destination, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        except Exception:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass
            raise
        return BackupInfo(final_path, created, entries, total)

    def inspect_backup(self, archive_path: pathlib.Path) -> BackupInfo:
        archive_file = _ensure_regular_file(archive_path)
        for root in self.roots:
            if root.path.exists():
                try:
                    archive_file.relative_to(root.path.resolve())
                except ValueError:
                    pass
                else:
                    raise BackupError("restore archive must be outside live SWIR data roots")
        if archive_file.stat().st_size > MAX_ARCHIVE_BYTES:
            raise BackupError("backup archive exceeds archive size limit")
        with zipfile.ZipFile(archive_file, "r") as archive:
            infos = archive.infolist()
            if len(infos) > MAX_FILES + 1:
                raise BackupError("backup archive has too many members")
            names = [info.filename for info in infos]
            if len(set(names)) != len(names):
                raise BackupError("backup archive contains duplicate member names")
            if names.count(MANIFEST_NAME) != 1:
                raise BackupError("backup manifest is missing or duplicated")
            manifest_info = next(info for info in infos if info.filename == MANIFEST_NAME)
            if manifest_info.file_size > 8 * 1024 * 1024:
                raise BackupError("backup manifest is unreasonably large")
            try:
                with archive.open(manifest_info, "r") as manifest_handle:
                    raw_manifest = manifest_handle.read(8 * 1024 * 1024 + 1)
                if len(raw_manifest) > 8 * 1024 * 1024:
                    raise BackupError("backup manifest is unreasonably large")
                manifest = json.loads(raw_manifest.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError, KeyError) as exc:
                raise BackupError("backup manifest is invalid") from exc
            if not isinstance(manifest, dict) or manifest.get("schema") != SCHEMA:
                raise BackupError("unsupported backup schema")
            created = manifest.get("createdAt")
            raw_entries = manifest.get("entries")
            roots = manifest.get("roots")
            if not isinstance(created, str) or not isinstance(raw_entries, list) or not isinstance(roots, list):
                raise BackupError("backup manifest fields are invalid")
            if set(roots) - {root.name for root in self.roots}:
                raise BackupError("backup contains an unsupported root")
            if len(raw_entries) > MAX_FILES:
                raise BackupError("backup manifest has too many files")

            entries: list[BackupEntry] = []
            expected_names = {MANIFEST_NAME}
            total = 0
            for raw in raw_entries:
                if not isinstance(raw, dict):
                    raise BackupError("backup manifest entry is invalid")
                root_name = raw.get("root")
                rel = raw.get("path")
                size = raw.get("size")
                digest = raw.get("sha256")
                if root_name not in {root.name for root in self.roots}:
                    raise BackupError("backup entry targets an unsupported root")
                if not isinstance(rel, str):
                    raise BackupError("backup entry path is invalid")
                _safe_component_path(rel)
                if not isinstance(size, int) or isinstance(size, bool) or not 0 <= size <= MAX_SINGLE_FILE_BYTES:
                    raise BackupError("backup entry size is invalid")
                if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
                    raise BackupError("backup entry digest is invalid")
                entry = BackupEntry(root_name, rel, size, digest)
                if entry.archive_name in expected_names:
                    raise BackupError("backup entry is duplicated")
                expected_names.add(entry.archive_name)
                total += size
                if total > MAX_TOTAL_BYTES:
                    raise BackupError("backup payload exceeds total data size limit")
                entries.append(entry)

            actual_names = set(names)
            if actual_names != expected_names:
                raise BackupError("backup contains unmanifested or missing members")

            info_map = {info.filename: info for info in infos}
            for entry in entries:
                info = info_map[entry.archive_name]
                unix_mode = (info.external_attr >> 16) & 0xFFFF
                if stat.S_ISLNK(unix_mode) or (unix_mode and not stat.S_ISREG(unix_mode)):
                    raise BackupError("backup contains a non-regular payload member")
                if info.flag_bits & 0x1:
                    raise BackupError("encrypted backup members are unsupported")
                if info.file_size != entry.size:
                    raise BackupError("backup member size does not match manifest")
                with archive.open(info, "r") as handle:
                    digest, observed = _sha256_stream(handle)
                if observed != entry.size or digest != entry.sha256:
                    raise BackupError("backup member digest does not match manifest")
        return BackupInfo(archive_file, created, tuple(entries), total)

    def restore_backup(self, archive_path: pathlib.Path) -> dict[str, str]:
        info = self.inspect_backup(archive_path)
        token = secrets.token_hex(8)
        root_map = {root.name: root for root in self.roots}
        staging: dict[str, pathlib.Path] = {}
        previous: dict[str, pathlib.Path] = {}
        committed: list[str] = []

        try:
            for root in self.roots:
                parent = _ensure_real_dir(root.path.parent, create=True)
                if root.path.exists() and (root.path.is_symlink() or not root.path.is_dir()):
                    raise BackupError(f"live SWIR root is unsafe: {root.path}")
                stage = parent / f".swir-restore-{token}-{root.name}"
                before = parent / f".swir-before-restore-{token}-{root.name}"
                if stage.exists() or before.exists():
                    raise BackupError("restore staging collision")
                stage.mkdir(mode=0o700)
                staging[root.name] = stage
                previous[root.name] = before

            with zipfile.ZipFile(info.path, "r") as archive:
                for entry in info.entries:
                    base = staging[entry.root]
                    parts = _safe_component_path(entry.relative_path).parts
                    current = base
                    for component in parts[:-1]:
                        current = current / component
                        if current.exists():
                            if current.is_symlink() or not current.is_dir():
                                raise BackupError("unsafe restore staging path")
                        else:
                            current.mkdir(mode=0o700)
                    target = current / parts[-1]
                    if target.exists() or target.is_symlink():
                        raise BackupError("restore target collision")
                    src = archive.open(entry.archive_name, "r")
                    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
                    digest = hashlib.sha256()
                    observed = 0
                    try:
                        with src, os.fdopen(fd, "wb", closefd=True) as out:
                            while True:
                                chunk = src.read(CHUNK_SIZE)
                                if not chunk:
                                    break
                                observed += len(chunk)
                                if observed > entry.size or observed > MAX_SINGLE_FILE_BYTES:
                                    raise BackupError("restore payload exceeded declared size")
                                digest.update(chunk)
                                out.write(chunk)
                            out.flush()
                            os.fsync(out.fileno())
                    except Exception:
                        try:
                            target.unlink(missing_ok=True)
                        except OSError:
                            pass
                        raise
                    if observed != entry.size or digest.hexdigest() != entry.sha256:
                        raise BackupError("restore payload failed digest verification")

            for root in self.roots:
                live = root.path
                stage = staging[root.name]
                before = previous[root.name]
                if live.exists():
                    os.rename(live, before)
                try:
                    os.rename(stage, live)
                except Exception:
                    if before.exists() and not live.exists():
                        os.rename(before, live)
                    raise
                committed.append(root.name)

            return {
                root_name: str(previous[root_name])
                for root_name in committed
                if previous[root_name].exists()
            }
        except Exception:
            for root_name in reversed(committed):
                root = root_map[root_name]
                live = root.path
                before = previous[root_name]
                failed = root.path.parent / f".swir-failed-restore-{token}-{root_name}"
                try:
                    if live.exists() and not failed.exists():
                        os.rename(live, failed)
                    if before.exists() and not live.exists():
                        os.rename(before, live)
                    if failed.exists():
                        shutil.rmtree(failed)
                except OSError:
                    pass
            raise
        finally:
            for stage in staging.values():
                if stage.exists() and not stage.is_symlink():
                    shutil.rmtree(stage, ignore_errors=True)


def self_test() -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="swir-backup-selftest-") as temp:
        base = pathlib.Path(temp)
        config = base / "config" / "swir"
        data = base / "data" / "swir"
        dest = base / "backups"
        config.mkdir(parents=True, mode=0o700)
        data.mkdir(parents=True, mode=0o700)
        (config / "settings.json").write_text('{"theme":"swir"}\n', encoding="utf-8")
        (data / "notes.txt").write_text("before\n", encoding="utf-8")
        os.chmod(config / "settings.json", 0o600)
        os.chmod(data / "notes.txt", 0o600)
        runtime = BackupRuntime((RootSpec("config", config), RootSpec("data", data)))
        backup = runtime.create_backup(dest)
        inspected = runtime.inspect_backup(backup.path)
        assert len(inspected.entries) == 2
        (config / "settings.json").write_text('{"theme":"changed"}\n', encoding="utf-8")
        (data / "notes.txt").write_text("changed\n", encoding="utf-8")
        previous = runtime.restore_backup(backup.path)
        assert (config / "settings.json").read_text(encoding="utf-8") == '{"theme":"swir"}\n'
        assert (data / "notes.txt").read_text(encoding="utf-8") == "before\n"
        assert set(previous) == {"config", "data"}
        assert _mode(backup.path) == 0o600
        hostile = data / "bad-link"
        hostile.symlink_to(config / "settings.json")
        try:
            runtime.create_backup(dest)
        except BackupError:
            symlink_rejected = True
        else:
            symlink_rejected = False
        assert symlink_rejected
        return {
            "schema": SCHEMA,
            "backupEntries": len(inspected.entries),
            "backupBytes": inspected.total_bytes,
            "restoreVerified": True,
            "symlinkRejected": True,
            "ownerOnlyArchive": True,
            "previousStatePreserved": True,
        }


if __name__ == "__main__":
    print(json.dumps(self_test(), sort_keys=True))
