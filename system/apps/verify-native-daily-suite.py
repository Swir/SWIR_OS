#!/usr/bin/env python3
"""Fail-closed integration verifier for the System Edition native daily-use suite.

This verifies that every Product Baseline 1.0 essential-utility capability is
represented by trusted native source, staged into the graphical image and
reachable from the native shell. It deliberately does not declare the umbrella
roadmap deliverable complete: per-application product-depth requirements remain
separate gates.
"""
from __future__ import annotations

import json
import pathlib
import re
import stat
import sys
from typing import Final

REPO = pathlib.Path(__file__).resolve().parents[2]
MANIFEST = REPO / "system/apps/native-daily-suite.json"
PROVISION = REPO / "system/session/provision-graphical-session.sh"
SHELL = REPO / "system/session/swir-shell.py"
BASELINE = REPO / "SWIR-PRODUCT-BASELINE-1.0.md"

EXPECTED_IDS: Final = frozenset(
    {
        "files",
        "settings",
        "terminal",
        "software",
        "updates",
        "hardware",
        "network",
        "browser",
        "notes",
        "player",
        "photo-studio",
        "pdf-viewer",
        "archive-manager",
        "calculator",
        "screenshot",
        "clock",
        "system-monitor",
        "logs-diagnostics",
        "backup-restore",
    }
)

# These tokens prove the verifier is looking at the intended native/security
# implementation rather than merely finding files with matching names.
REQUIRED_MARKERS: Final = {
    "browser": ("gi.require_version(\"Gtk\", \"4.0\")", "WebKit"),
    "player": ("gi.require_version(\"Gtk\", \"4.0\")", "Gst"),
    "photo-studio": ("GdkPixbuf", "EditHistory", "_atomic_export"),
    "pdf-viewer": ("Poppler", "gi.require_version(\"Gtk\", \"4.0\")"),
    "archive-manager": ("_safe_member_parts", "O_NOFOLLOW", "O_EXCL", "--archive-self-test"),
    "terminal": ("Vte", "gi.require_version(\"Gtk\", \"4.0\")"),
    "screenshot": ("org.freedesktop.portal.Screenshot", "_validated_portal_uri", "O_NOFOLLOW"),
    "system-monitor": ("ProcessIdentity", "start_ticks", "SIGTERM"),
    "logs-diagnostics": ("JOURNALCTL_PATH", "SYSTEMCTL_PATH", "ALLOWED_DIAGNOSTIC_COMMANDS"),
    "backup-restore": ("backup_runtime", "gi.require_version(\"Gtk\", \"4.0\")"),
}

FORBIDDEN_SOURCE_SUFFIXES: Final = {".html", ".htm", ".js", ".mjs", ".css"}


def fail(message: str) -> None:
    raise SystemExit(f"native daily suite verification failed: {message}")


def trusted_repo_file(relative: str) -> pathlib.Path:
    if not isinstance(relative, str) or not relative or relative.startswith("/"):
        fail(f"invalid repository path: {relative!r}")
    pure = pathlib.PurePosixPath(relative)
    if ".." in pure.parts or "." in pure.parts:
        fail(f"unsafe repository path: {relative}")
    target = REPO.joinpath(*pure.parts)
    try:
        st = target.lstat()
    except FileNotFoundError:
        fail(f"required file missing: {relative}")
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode):
        fail(f"required file is not a regular non-symlink file: {relative}")
    resolved = target.resolve(strict=True)
    try:
        resolved.relative_to(REPO.resolve(strict=True))
    except ValueError:
        fail(f"required file escaped repository root: {relative}")
    return resolved


def load_manifest() -> dict:
    manifest_path = trusted_repo_file("system/apps/native-daily-suite.json")
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        fail(f"manifest cannot be parsed: {exc}")
    if data.get("schema") != "swir.native-daily-suite/1.0":
        fail("unexpected manifest schema")
    if data.get("sourceOfTruth") != "SWIR-PRODUCT-BASELINE-1.0.md#6-essential-utilities":
        fail("manifest source-of-truth reference changed")
    capabilities = data.get("capabilities")
    if not isinstance(capabilities, list):
        fail("manifest capabilities must be an array")
    ids = [item.get("id") for item in capabilities if isinstance(item, dict)]
    if len(ids) != len(capabilities) or len(ids) != len(set(ids)):
        fail("capability ids are missing or duplicated")
    if set(ids) != EXPECTED_IDS:
        fail(f"capability coverage mismatch: missing={sorted(EXPECTED_IDS-set(ids))} extra={sorted(set(ids)-EXPECTED_IDS)}")
    return data


def verify_baseline_reference() -> None:
    text = trusted_repo_file("SWIR-PRODUCT-BASELINE-1.0.md").read_text(encoding="utf-8")
    required_labels = (
        "File Manager", "Settings / Control Center", "Terminal", "Software / SWIR Store",
        "Update Center", "Hardware & Driver Center", "Network Center", "SWIR Browser",
        "Text Editor / Notes", "SWIR Player", "SWIR Photo Studio / Image Viewer", "PDF Viewer",
        "Archive Manager", "Calculator", "Screenshot tool", "Clock / alarms / calendar basics",
        "Task Manager / System Monitor", "Logs / Diagnostics", "Backup / Restore and recovery entry points",
    )
    for label in required_labels:
        if f"- {label}" not in text:
            fail(f"Product Baseline essential-utility label changed or disappeared: {label}")


def verify_source(capability: dict) -> None:
    ident = capability["id"]
    source = capability.get("source")
    stage = capability.get("stage")
    launcher = capability.get("launcher")
    if not isinstance(source, str) or not source.startswith("system/apps/"):
        fail(f"{ident}: source must live under system/apps")
    if pathlib.PurePosixPath(source).suffix in FORBIDDEN_SOURCE_SUFFIXES or not source.endswith(".py"):
        fail(f"{ident}: essential utility is not represented by native Python/GTK source")
    if not isinstance(stage, str) or not stage.startswith("/usr/local/bin/swir-") or ".." in stage:
        fail(f"{ident}: unsafe or unexpected staged executable path")
    if not isinstance(launcher, str) or not launcher.strip():
        fail(f"{ident}: launcher label missing")

    path = trusted_repo_file(source)
    raw = path.read_text(encoding="utf-8")
    if not raw.startswith("#!/usr/bin/env python3\n"):
        fail(f"{ident}: native app source lacks the trusted python3 shebang")
    try:
        compile(raw, source, "exec")
    except SyntaxError as exc:
        fail(f"{ident}: source does not compile: {exc}")
    if "gi.require_version(\"Gtk\", \"4.0\")" not in raw:
        fail(f"{ident}: source is not a verified GTK4 application/integration")
    for marker in REQUIRED_MARKERS.get(ident, ()):
        if marker not in raw:
            fail(f"{ident}: required implementation marker missing: {marker}")

    for companion in capability.get("companions", []):
        if not isinstance(companion, str):
            fail(f"{ident}: malformed companion path")
        trusted_repo_file(companion)


def verify_image_and_shell_integration(capabilities: list[dict]) -> None:
    provision = trusted_repo_file("system/session/provision-graphical-session.sh").read_text(encoding="utf-8")
    shell = trusted_repo_file("system/session/swir-shell.py").read_text(encoding="utf-8")
    if "set -euo pipefail" not in provision:
        fail("graphical provisioning no longer uses fail-closed shell flags")
    if "LAUNCHERS: Final" not in shell:
        fail("native shell launcher allowlist is missing")

    unique_pairs: set[tuple[str, str]] = set()
    for cap in capabilities:
        source = cap["source"]
        stage = cap["stage"]
        unique_pairs.add((source, stage))
        expected_launcher = f'(\"{cap["launcher"]}\",'
        if expected_launcher not in shell or stage not in shell:
            fail(f'{cap["id"]}: fixed native shell launcher is missing')
        mode_arg = cap.get("modeArg")
        if mode_arg and mode_arg not in shell:
            fail(f'{cap["id"]}: launcher mode argument is missing')

    for source, stage in unique_pairs:
        source_token = f'$SOURCE_ROOT/{source}'
        target_token = f'safe_target {stage}'
        if source_token not in provision or target_token not in provision:
            fail(f"graphical image does not stage {source} -> {stage}")
        if stage not in provision:
            fail(f"graphical image compile/trust gate does not reference {stage}")

    if "native-apps=" not in provision:
        fail("graphical provisioning evidence summary lost native app inventory")


def verify_no_web_payloads(capabilities: list[dict]) -> None:
    for cap in capabilities:
        paths = [cap["source"], *cap.get("companions", [])]
        for item in paths:
            suffix = pathlib.PurePosixPath(item).suffix.lower()
            if suffix in FORBIDDEN_SOURCE_SUFFIXES:
                fail(f"{cap['id']}: browser/web payload entered essential System Edition suite: {item}")


def main() -> int:
    verify_baseline_reference()
    data = load_manifest()
    caps = data["capabilities"]
    for capability in caps:
        verify_source(capability)
    verify_no_web_payloads(caps)
    verify_image_and_shell_integration(caps)
    summary = {
        "schema": "swir.native-daily-suite-verification/1.0",
        "passed": True,
        "scope": data["scope"],
        "capabilityCount": len(caps),
        "baselineCapabilityCount": len(EXPECTED_IDS),
        "nativeSourceOnly": True,
        "graphicalImageStagingVerified": True,
        "nativeShellReachabilityVerified": True,
        "roadmapCompletionClaimed": False,
    }
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
