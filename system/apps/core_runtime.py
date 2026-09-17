#!/usr/bin/env python3
"""Shared unprivileged runtime helpers for native SWIR System Edition apps.

The helpers in this module intentionally avoid privileged mutation. They provide
small, testable filesystem and per-user settings primitives used by first-party
GTK applications. Privileged system configuration remains behind dedicated
brokers and Polkit policies.
"""

from __future__ import annotations

import json
import os
import pathlib
import re
import tempfile
from dataclasses import dataclass
from typing import Final

SETTINGS_SCHEMA: Final = "swir.user-settings/0.1"
MAX_SETTINGS_BYTES: Final = 64 * 1024
_LANGUAGE_RE: Final = re.compile(r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$")
_ALLOWED_APPEARANCE: Final = frozenset({"dark", "system"})


@dataclass(frozen=True)
class DirectoryEntry:
    name: str
    kind: str
    size: int | None
    hidden: bool


def resolve_directory(value: str | os.PathLike[str] | None, *, fallback: pathlib.Path | None = None) -> pathlib.Path:
    """Resolve a readable directory without performing any mutation."""

    candidate = pathlib.Path(value).expanduser() if value else (fallback or pathlib.Path.home())
    resolved = candidate.resolve(strict=True)
    if not resolved.is_dir():
        raise NotADirectoryError(str(resolved))
    if not os.access(resolved, os.R_OK | os.X_OK):
        raise PermissionError(str(resolved))
    return resolved


def list_directory(path: pathlib.Path, *, include_hidden: bool = False) -> list[DirectoryEntry]:
    """Return a deterministic read-only directory snapshot.

    Symlinks are reported as symlinks instead of being followed. Directory
    navigation is an explicit later user action which resolves the selected
    target again through ``resolve_directory``.
    """

    directory = resolve_directory(path)
    rows: list[DirectoryEntry] = []
    with os.scandir(directory) as iterator:
        for item in iterator:
            hidden = item.name.startswith(".")
            if hidden and not include_hidden:
                continue
            try:
                if item.is_symlink():
                    kind = "symlink"
                    size = None
                elif item.is_dir(follow_symlinks=False):
                    kind = "directory"
                    size = None
                elif item.is_file(follow_symlinks=False):
                    kind = "file"
                    size = item.stat(follow_symlinks=False).st_size
                else:
                    kind = "other"
                    size = None
            except OSError:
                kind = "unavailable"
                size = None
            rows.append(DirectoryEntry(item.name, kind, size, hidden))
    rows.sort(key=lambda row: (row.kind != "directory", row.name.casefold(), row.name))
    return rows


def default_settings() -> dict[str, object]:
    return {
        "schema": SETTINGS_SCHEMA,
        "appearance": "dark",
        "language": "en",
        "clock24h": True,
    }


def validate_settings(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError("settings must be an object")
    result = default_settings()
    if value.get("schema", SETTINGS_SCHEMA) != SETTINGS_SCHEMA:
        raise ValueError("unsupported settings schema")

    appearance = value.get("appearance", result["appearance"])
    language = value.get("language", result["language"])
    clock24h = value.get("clock24h", result["clock24h"])

    if appearance not in _ALLOWED_APPEARANCE:
        raise ValueError("unsupported appearance")
    if not isinstance(language, str) or not _LANGUAGE_RE.fullmatch(language):
        raise ValueError("invalid BCP-47 language tag")
    if not isinstance(clock24h, bool):
        raise ValueError("clock24h must be boolean")

    result.update(appearance=appearance, language=language, clock24h=clock24h)
    return result


class UserSettingsStore:
    """Owner-only, atomic storage for non-privileged SWIR user preferences."""

    def __init__(self, config_home: pathlib.Path | None = None) -> None:
        if config_home is None:
            raw = os.environ.get("XDG_CONFIG_HOME")
            config_home = pathlib.Path(raw).expanduser() if raw else pathlib.Path.home() / ".config"
        self.config_home = config_home.resolve(strict=False)
        self.directory = self.config_home / "swir"
        self.path = self.directory / "settings.json"

    def _prepare_directory(self) -> None:
        if self.directory.is_symlink():
            raise RuntimeError("refusing symlinked SWIR settings directory")
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        if self.directory.is_symlink() or not self.directory.is_dir():
            raise RuntimeError("invalid SWIR settings directory")
        os.chmod(self.directory, 0o700)

    def load(self) -> dict[str, object]:
        if self.path.is_symlink():
            raise RuntimeError("refusing symlinked settings file")
        if not self.path.exists():
            return default_settings()
        if not self.path.is_file():
            raise RuntimeError("refusing non-regular settings file")
        data = self.path.read_bytes()
        if len(data) > MAX_SETTINGS_BYTES:
            raise ValueError("settings file exceeds size limit")
        return validate_settings(json.loads(data.decode("utf-8")))

    def save(self, value: object) -> dict[str, object]:
        payload = validate_settings(value)
        self._prepare_directory()
        encoded = (json.dumps(payload, sort_keys=True, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        if len(encoded) > MAX_SETTINGS_BYTES:
            raise ValueError("settings payload exceeds size limit")

        fd, temporary = tempfile.mkstemp(prefix=".settings-", suffix=".tmp", dir=self.directory)
        tmp_path = pathlib.Path(temporary)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "wb", closefd=True) as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            if tmp_path.is_symlink():
                raise RuntimeError("temporary settings path became a symlink")
            if self.path.is_symlink():
                raise RuntimeError("refusing to replace symlinked settings file")
            os.replace(tmp_path, self.path)
            os.chmod(self.path, 0o600)
            dir_fd = os.open(self.directory, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        finally:
            if tmp_path.exists():
                tmp_path.unlink()
        return payload
