#!/usr/bin/env python3
"""Verify a pair of physical SWIR OS Live/installed evidence snapshots.

Passing this verifier means the evidence is internally consistent with a
physical UEFI USB -> installed-disk -> detached-USB sequence. It intentionally
does not mark the physical-hardware roadmap gate complete; destructive-target
safety observations and human review remain separate.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import hmac
import json
import pathlib
import stat
import sys
from typing import Any, Final

SCHEMA: Final = "swir.physical-live-usb-evidence/1.0"
MAX_EVIDENCE_BYTES: Final = 2 * 1024 * 1024


def fail(message: str) -> "NoReturn":
    raise SystemExit(f"physical evidence verification failed: {message}")


def load_regular_json(path_text: str) -> dict[str, Any]:
    path = pathlib.Path(path_text)
    try:
        st = path.lstat()
    except OSError as exc:
        fail(f"cannot stat evidence file {path}: {exc}")
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode):
        fail(f"evidence input must be a regular non-symlink file: {path}")
    if st.st_size <= 0 or st.st_size > MAX_EVIDENCE_BYTES:
        fail(f"evidence file size is outside the accepted range: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        fail(f"cannot parse evidence file {path}: {exc}")
    if not isinstance(data, dict):
        fail(f"evidence root must be an object: {path}")
    return data


def verify_digest(data: dict[str, Any], label: str) -> None:
    actual = data.get("evidenceDigestSha256")
    if not isinstance(actual, str) or len(actual) != 64:
        fail(f"{label}: missing evidence digest")
    payload = dict(data)
    payload.pop("evidenceDigestSha256", None)
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    expected = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    if not hmac.compare_digest(actual, expected):
        fail(f"{label}: evidence digest mismatch")


def parse_timestamp(value: Any, label: str) -> dt.datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        fail(f"{label}: capturedAtUtc must be an RFC3339 UTC timestamp")
    try:
        parsed = dt.datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        fail(f"{label}: malformed capturedAtUtc: {exc}")
    return parsed


def same_hardware_identity(live: dict[str, Any], installed: dict[str, Any]) -> bool:
    live_system = live.get("system") or {}
    installed_system = installed.get("system") or {}
    live_dmi = live_system.get("dmi") or {}
    installed_dmi = installed_system.get("dmi") or {}
    identity_fields = ("sysVendor", "productName", "productVersion")
    return (
        all((live_dmi.get(key) or "") == (installed_dmi.get(key) or "") for key in identity_fields)
        and live_system.get("architecture") == installed_system.get("architecture")
    )


def verify_pair(live: dict[str, Any], installed: dict[str, Any]) -> dict[str, Any]:
    """Validate an already-loaded Live/installed pair and return the safe summary."""
    for label, data, phase in (("live", live, "live"), ("installed", installed, "installed")):
        if data.get("schema") != SCHEMA:
            fail(f"{label}: unexpected schema")
        if data.get("phase") != phase:
            fail(f"{label}: expected phase {phase!r}")
        verify_digest(data, label)
        claims = data.get("claims") or {}
        if claims.get("physicalHardwareQualificationClaim") is not False:
            fail(f"{label}: collector must not self-claim physical qualification")
        system = data.get("system") or {}
        if system.get("virtualizationHeuristic") is not False:
            fail(f"{label}: virtualized or ambiguous evidence cannot qualify as a physical sequence")
        if system.get("bootMode") != "uefi":
            fail(f"{label}: only the currently tested UEFI path is accepted")

    if (live.get("liveUsbEvidence") or {}).get("physicalCandidate") is not True:
        fail("live: evidence is not a physical USB candidate")
    if (live.get("liveUsbEvidence") or {}).get("rootParentTransportIsUsb") is not True:
        fail("live: root parent is not USB")
    if (installed.get("installedBootEvidence") or {}).get("installedCandidate") is not True:
        fail("installed: evidence is not a detached installed-boot candidate")
    if (installed.get("installedBootEvidence") or {}).get("rootParentTransportIsUsb") is not False:
        fail("installed: root still appears to come from USB")

    live_marker = (live.get("installedBootEvidence") or {}).get("persistenceMarkerSha256")
    installed_marker = (installed.get("installedBootEvidence") or {}).get("persistenceMarkerSha256")
    if not live_marker or not installed_marker or live_marker != installed_marker:
        fail("persistence marker is missing or changed between Live and installed boot")

    if not same_hardware_identity(live, installed):
        fail("Live and installed evidence do not describe the same hardware identity")

    live_time = parse_timestamp(live.get("capturedAtUtc"), "live")
    installed_time = parse_timestamp(installed.get("capturedAtUtc"), "installed")
    if installed_time < live_time:
        fail("installed evidence predates Live evidence")

    return {
        "schema": "swir.physical-live-usb-sequence-verification/1.0",
        "passed": True,
        "sameHardwareIdentity": True,
        "liveUsbBootCandidateVerified": True,
        "detachedInstalledBootCandidateVerified": True,
        "persistenceMarkerContinuityVerified": True,
        "uefiOnly": True,
        "secureBootSupportClaim": False,
        "legacyBiosSupportClaim": False,
        "physicalHardwareRoadmapCompletionClaimed": False,
        "remainingReview": [
            "source-USB target refusal on physical hardware",
            "cancel and wrong-confirmation paths leave the physical target unchanged",
            "human-reviewed install to an explicitly identified empty test disk",
            "device-specific graphics, network, audio, suspend/resume and firmware qualification",
        ],
    }


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", required=True)
    parser.add_argument("--installed", required=True)
    args = parser.parse_args(argv)

    summary = verify_pair(load_regular_json(args.live), load_regular_json(args.installed))
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
