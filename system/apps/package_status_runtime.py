#!/usr/bin/env python3
"""Read-only package metadata helpers for native SWIR System Edition apps.

This module deliberately exposes no package mutation. It reads local Debian
package metadata through fixed absolute executables with bounded queries and
returns small typed snapshots for the Software Center and Update Center UIs.
Privileged installation/update work stays behind the existing SWIR package
transaction service and Polkit boundary.
"""

from __future__ import annotations

import os
import pathlib
import re
import subprocess
from dataclasses import dataclass
from typing import Final

APT_CACHE: Final = pathlib.Path("/usr/bin/apt-cache")
APT_GET: Final = pathlib.Path("/usr/bin/apt-get")
DPKG_QUERY: Final = pathlib.Path("/usr/bin/dpkg-query")
QUERY_TIMEOUT_SECONDS: Final = 8
MAX_PACKAGE_ROWS: Final = 200
MAX_UPDATE_ROWS: Final = 200
MAX_CAPTURE_CHARS: Final = 256 * 1024
MAX_SEARCH_CHARS: Final = 64
_ALLOWED_EXECUTABLES: Final = frozenset({APT_CACHE, APT_GET, DPKG_QUERY})
_UPDATE_RE: Final = re.compile(r"^Inst\s+(?P<name>\S+)(?:\s+\[(?P<current>[^\]]+)\])?\s+\((?P<candidate>\S+)")


@dataclass(frozen=True)
class PackageRow:
    name: str
    version: str
    description: str = ""


@dataclass(frozen=True)
class UpdateRow:
    name: str
    current_version: str
    candidate_version: str


@dataclass(frozen=True)
class UpdateSnapshot:
    rows: tuple[UpdateRow, ...]
    ok: bool
    message: str
    truncated: bool


def _tool_ready(path: pathlib.Path) -> bool:
    return path.is_file() and not path.is_symlink() and os.access(path, os.X_OK)


def tools_status() -> dict[str, bool]:
    return {
        "aptCache": _tool_ready(APT_CACHE),
        "aptGet": _tool_ready(APT_GET),
        "dpkgQuery": _tool_ready(DPKG_QUERY),
    }


def _run_read_only(executable: pathlib.Path, arguments: tuple[str, ...]) -> tuple[bool, str]:
    if executable not in _ALLOWED_EXECUTABLES:
        raise ValueError("package status runtime refused non-allowlisted executable")
    if not _tool_ready(executable):
        return False, f"{executable.name} is unavailable"
    try:
        completed = subprocess.run(
            (str(executable), *arguments),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            close_fds=True,
            check=False,
            timeout=QUERY_TIMEOUT_SECONDS,
            env={**os.environ, "LC_ALL": "C", "LANG": "C"},
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"package metadata query failed: {exc}"

    stdout = completed.stdout[:MAX_CAPTURE_CHARS]
    if completed.returncode != 0:
        detail = (completed.stderr.strip() or stdout.strip() or f"exit {completed.returncode}")[:1000]
        return False, detail
    return True, stdout


def list_installed(limit: int = MAX_PACKAGE_ROWS) -> tuple[list[PackageRow], bool, str]:
    limit = max(1, min(int(limit), MAX_PACKAGE_ROWS))
    ok, output = _run_read_only(DPKG_QUERY, ("-W", "-f=${binary:Package}\t${Version}\n"))
    if not ok:
        return [], False, output
    rows: list[PackageRow] = []
    for line in output.splitlines():
        if not line or "\t" not in line:
            continue
        name, version = line.split("\t", 1)
        name = name.strip()[:160]
        version = version.strip()[:240]
        if not name:
            continue
        rows.append(PackageRow(name=name, version=version))
        if len(rows) >= limit:
            break
    return rows, True, ""


def normalize_search_term(value: str) -> str:
    value = " ".join(value.strip().split())
    if not value:
        raise ValueError("enter a package name or keyword")
    if len(value) > MAX_SEARCH_CHARS:
        raise ValueError(f"search is limited to {MAX_SEARCH_CHARS} characters")
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ValueError("search contains control characters")
    return value


def search_available(value: str, limit: int = MAX_PACKAGE_ROWS) -> tuple[list[PackageRow], bool, str]:
    term = normalize_search_term(value)
    limit = max(1, min(int(limit), MAX_PACKAGE_ROWS))
    # apt-cache accepts a regular expression. Escape the user term so search
    # remains literal and cannot trigger pathological caller-controlled regexes.
    pattern = re.escape(term)
    ok, output = _run_read_only(APT_CACHE, ("search", pattern))
    if not ok:
        return [], False, output
    rows: list[PackageRow] = []
    for line in output.splitlines():
        if " - " not in line:
            continue
        name, description = line.split(" - ", 1)
        name = name.strip()[:160]
        if not name:
            continue
        rows.append(PackageRow(name=name, version="available", description=description.strip()[:360]))
        if len(rows) >= limit:
            break
    return rows, True, ""


def parse_simulated_upgrade(output: str, limit: int = MAX_UPDATE_ROWS) -> tuple[list[UpdateRow], bool]:
    limit = max(1, min(int(limit), MAX_UPDATE_ROWS))
    rows: list[UpdateRow] = []
    truncated = False
    for line in output.splitlines():
        match = _UPDATE_RE.match(line)
        if match is None:
            continue
        if len(rows) >= limit:
            truncated = True
            break
        rows.append(
            UpdateRow(
                name=match.group("name")[:160],
                current_version=(match.group("current") or "unknown")[:240],
                candidate_version=match.group("candidate")[:240],
            )
        )
    return rows, truncated


def read_update_snapshot(limit: int = MAX_UPDATE_ROWS) -> UpdateSnapshot:
    # --simulate performs no package mutation. Debug::NoLocking avoids taking an
    # exclusive dpkg/apt lock for this read-only preview. No metadata refresh or
    # network access is initiated here.
    ok, output = _run_read_only(
        APT_GET,
        ("--simulate", "--no-download", "-o", "Debug::NoLocking=true", "dist-upgrade"),
    )
    if not ok:
        return UpdateSnapshot(rows=(), ok=False, message=output, truncated=False)
    rows, truncated = parse_simulated_upgrade(output, limit)
    message = "Local package metadata checked; no upgrades are currently planned." if not rows else ""
    return UpdateSnapshot(rows=tuple(rows), ok=True, message=message, truncated=truncated)
