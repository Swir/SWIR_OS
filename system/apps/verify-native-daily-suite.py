#!/usr/bin/env python3
"""Fail-closed integration verifier for the System Edition native daily-use suite.

This verifies that every Product Baseline 1.0 essential-utility capability is
represented by trusted native source, staged into the graphical image,
reachable through an explicitly verified native entry point, and bound to an
in-repository runtime-evidence workflow. It deliberately does not declare the
umbrella roadmap deliverable complete: per-application product-depth
requirements remain separate gates.
"""
from __future__ import annotations

import json
import pathlib
import stat
from typing import Final

REPO = pathlib.Path(__file__).resolve().parents[2]

EXPECTED_IDS: Final = frozenset(
    {
        "files", "settings", "terminal", "software", "updates", "hardware",
        "network", "browser", "text-editor", "notes", "player", "photo-studio",
        "pdf-viewer", "archive-manager", "calculator", "screenshot", "clock",
        "system-monitor", "logs-diagnostics", "backup-restore",
    }
)

# These tokens prove the verifier is looking at the intended native/security
# implementation rather than merely finding files with matching names.
REQUIRED_MARKERS: Final = {
    "browser": ("gi.require_version(\"Gtk\", \"4.0\")", "WebKit"),
    "text-editor": (
        "Gio.ApplicationFlags.HANDLES_OPEN",
        "os.O_EXCL",
        "O_NOFOLLOW",
        "os.replace(temp, path)",
        "Gtk.FileChooserNative",
        "swir.native-text-editor-runtime-evidence/0.2",
    ),
    "player": ("gi.require_version(\"Gtk\", \"4.0\")", "Gst"),
    "photo-studio": (
        "GdkPixbuf", "EditHistory", "_atomic_export", "def _crop_pixbuf(",
        "def _transform_pixels(", "def _annotate_text(", "def _draw_line(",
        "swir.native-photo-studio-runtime-evidence/0.4",
    ),
    "pdf-viewer": ("Poppler", "gi.require_version(\"Gtk\", \"4.0\")"),
    "archive-manager": ("_safe_member_parts", "O_NOFOLLOW", "O_EXCL", "--archive-self-test"),
    "terminal": ("Vte", "gi.require_version(\"Gtk\", \"4.0\")"),
    "screenshot": ("org.freedesktop.portal.Screenshot", "_validated_portal_uri", "O_NOFOLLOW"),
    "system-monitor": ("ProcessIdentity", "start_ticks", "SIGTERM"),
    "logs-diagnostics": ("JOURNALCTL_PATH", "SYSTEMCTL_PATH", "ALLOWED_DIAGNOSTIC_COMMANDS"),
    "backup-restore": ("backup_runtime", "gi.require_version(\"Gtk\", \"4.0\")"),
}

FORBIDDEN_APP_SOURCE_SUFFIXES: Final = {".html", ".htm", ".js", ".mjs", ".css"}
ALLOWED_COMPANION_SUFFIXES: Final = {".py", ".mjs", ".service", ".target", ".json"}
RUNTIME_EVIDENCE_MARKERS: Final = (
    "SWIR_APP_E2E",
    "SWIR_APP_EVIDENCE_PATH",
    "wayland-runtime",
    "--archive-self-test",
    "selftest",
)
DEFAULT_APP_TYPES: Final = {
    "text": (
        "text/plain",
        "text/markdown",
        "application/json",
        "text/x-python",
    ),
}
DEFAULT_APP_FIRST_PARTY_IDS: Final = {"text": "swir-text-editor.desktop"}


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

    photo_required = (
        "crop, rotate/flip, resize, exposure/brightness/contrast, color controls, filters, text, drawing/annotation, undo/redo",
        "explicit save/export behavior",
    )
    for marker in photo_required:
        if marker not in text:
            fail(f"Photo Studio Product Baseline depth changed or disappeared: {marker}")


def verify_evidence_workflow(capability: dict) -> str:
    ident = capability["id"]
    source = capability["source"]
    workflow = capability.get("evidenceWorkflow")
    if not isinstance(workflow, str):
        fail(f"{ident}: runtime evidence workflow is missing")
    pure = pathlib.PurePosixPath(workflow)
    if pure.parent != pathlib.PurePosixPath(".github/workflows") or pure.suffix not in {".yml", ".yaml"}:
        fail(f"{ident}: runtime evidence workflow must live under .github/workflows: {workflow!r}")

    workflow_text = trusted_repo_file(workflow).read_text(encoding="utf-8")
    if source not in workflow_text:
        fail(f"{ident}: runtime evidence workflow does not reference its native source: {workflow}")
    if "pull_request:" not in workflow_text:
        fail(f"{ident}: runtime evidence workflow is not a pull-request gate: {workflow}")
    if "runs-on:" not in workflow_text:
        fail(f"{ident}: runtime evidence workflow has no executable job: {workflow}")
    if "permissions:" not in workflow_text or "contents: read" not in workflow_text:
        fail(f"{ident}: runtime evidence workflow lost its read-only contents permission: {workflow}")
    if not any(marker in workflow_text for marker in RUNTIME_EVIDENCE_MARKERS):
        fail(f"{ident}: runtime evidence workflow lacks a recognized runtime/self-test marker: {workflow}")
    return workflow


def verify_source(capability: dict) -> str:
    ident = capability["id"]
    source = capability.get("source")
    stage = capability.get("stage")
    launcher = capability.get("launcher")
    if not isinstance(source, str) or not source.startswith("system/apps/"):
        fail(f"{ident}: source must live under system/apps")
    if pathlib.PurePosixPath(source).suffix in FORBIDDEN_APP_SOURCE_SUFFIXES or not source.endswith(".py"):
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
        if pathlib.PurePosixPath(companion).suffix.lower() not in ALLOWED_COMPANION_SUFFIXES:
            fail(f"{ident}: unexpected recovery/system companion type: {companion}")
        trusted_repo_file(companion)

    return verify_evidence_workflow(capability)


def verify_default_app_reachability(capability: dict, provision: str, settings: str) -> None:
    ident = capability["id"]
    reachability = capability.get("reachability")
    if not isinstance(reachability, dict) or set(reachability) != {"kind", "category"}:
        fail(f"{ident}: malformed explicit reachability policy")
    if reachability.get("kind") != "default-app":
        fail(f"{ident}: unsupported reachability kind")
    category = reachability.get("category")
    if category not in DEFAULT_APP_TYPES:
        fail(f"{ident}: unsupported Default Apps category: {category!r}")

    desktop = capability.get("desktop")
    if not isinstance(desktop, str) or pathlib.PurePosixPath(desktop).parent != pathlib.PurePosixPath("system/apps"):
        fail(f"{ident}: native desktop registration is missing")
    desktop_path = trusted_repo_file(desktop)
    desktop_name = desktop_path.name
    if DEFAULT_APP_FIRST_PARTY_IDS[category] != desktop_name:
        fail(f"{ident}: unexpected first-party desktop id for {category}")
    desktop_text = desktop_path.read_text(encoding="utf-8")
    stage = capability["stage"]
    if f"Exec={stage} %f" not in desktop_text or f"TryExec={stage}" not in desktop_text:
        fail(f"{ident}: desktop registration is not bound to the staged executable")
    if f"Name=SWIR {capability['launcher']}" not in desktop_text:
        fail(f"{ident}: desktop registration lost its first-party display identity")
    for mime in DEFAULT_APP_TYPES[category]:
        if mime not in desktop_text:
            fail(f"{ident}: desktop registration lost required handler type {mime}")

    if desktop not in provision or f"safe_target /usr/share/applications/{desktop_name}" not in provision:
        fail(f"{ident}: graphical image does not stage the desktop registration")
    settings_binding = f'"{category}": "{desktop_name}"'
    if settings_binding not in settings:
        fail(f"{ident}: Settings no longer binds the first-party Default Apps handler")
    for mime in DEFAULT_APP_TYPES[category]:
        if mime not in settings:
            fail(f"{ident}: Settings lost required Default Apps handler type {mime}")


def verify_image_and_shell_integration(capabilities: list[dict]) -> int:
    provision = trusted_repo_file("system/session/provision-graphical-session.sh").read_text(encoding="utf-8")
    shell = trusted_repo_file("system/session/swir-shell.py").read_text(encoding="utf-8")
    settings = trusted_repo_file("system/apps/swir-settings.py").read_text(encoding="utf-8")
    if "set -euo pipefail" not in provision:
        fail("graphical provisioning no longer uses fail-closed shell flags")
    if "LAUNCHERS: Final" not in shell:
        fail("native shell launcher allowlist is missing")

    unique_pairs: set[tuple[str, str]] = set()
    default_app_reachability = 0
    for cap in capabilities:
        source = cap["source"]
        stage = cap["stage"]
        unique_pairs.add((source, stage))
        reachability = cap.get("reachability")
        if reachability is None:
            expected_launcher = f'(\"{cap["launcher"]}\",'
            if expected_launcher not in shell or stage not in shell:
                fail(f'{cap["id"]}: fixed native shell launcher is missing')
            mode_arg = cap.get("modeArg")
            if mode_arg and mode_arg not in shell:
                fail(f'{cap["id"]}: launcher mode argument is missing')
        else:
            verify_default_app_reachability(cap, provision, settings)
            default_app_reachability += 1

    for source, stage in unique_pairs:
        source_token = f'$SOURCE_ROOT/{source}'
        target_token = f'safe_target {stage}'
        if source_token not in provision or target_token not in provision:
            fail(f"graphical image does not stage {source} -> {stage}")
        if stage not in provision:
            fail(f"graphical image compile/trust gate does not reference {stage}")

    if "native-apps=" not in provision:
        fail("graphical provisioning evidence summary lost native app inventory")
    return default_app_reachability


def verify_no_web_app_sources(capabilities: list[dict]) -> None:
    for cap in capabilities:
        source = cap["source"]
        if pathlib.PurePosixPath(source).suffix.lower() in FORBIDDEN_APP_SOURCE_SUFFIXES:
            fail(f"{cap['id']}: browser/web payload entered essential System Edition app source: {source}")


def main() -> int:
    verify_baseline_reference()
    data = load_manifest()
    caps = data["capabilities"]
    evidence_workflows: set[str] = set()
    for capability in caps:
        evidence_workflows.add(verify_source(capability))
    verify_no_web_app_sources(caps)
    default_reachability = verify_image_and_shell_integration(caps)
    summary = {
        "schema": "swir.native-daily-suite-verification/1.1",
        "passed": True,
        "scope": data["scope"],
        "capabilityCount": len(caps),
        "explicitImplementationCapabilityCount": len(EXPECTED_IDS),
        "nativeSourceOnly": True,
        "graphicalImageStagingVerified": True,
        "nativeReachabilityVerified": True,
        "fixedShellReachabilityCount": len(caps) - default_reachability,
        "defaultAppReachabilityCount": default_reachability,
        "runtimeEvidenceCoverageVerified": True,
        "runtimeEvidenceCapabilityCount": len(caps),
        "runtimeEvidenceWorkflowCount": len(evidence_workflows),
        "photoStudioBaselineDepthMarkersVerified": True,
        "roadmapCompletionClaimed": False,
    }
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
