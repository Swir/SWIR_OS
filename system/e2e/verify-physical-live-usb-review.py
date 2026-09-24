#!/usr/bin/env python3
"""Fail-closed review gate for a physical SWIR OS Live USB qualification run.

This verifier binds an explicit operator review to the exact Live and installed
collector evidence digests and to the exact final image SHA-256/source commit.
It never performs destructive actions and never marks the roadmap complete by
itself; a passing result is review-ready evidence for a human integration gate.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import hmac
import importlib.util
import json
import pathlib
import re
import stat
import sys
from typing import Any, Final

REVIEW_SCHEMA: Final = "swir.physical-live-usb-review/1.0"
MAX_REVIEW_BYTES: Final = 512 * 1024
HEX64: Final = re.compile(r"^[0-9a-f]{64}$")
HEX40: Final = re.compile(r"^[0-9a-f]{40}$")
REQUIRED_OBSERVATIONS: Final = (
    "finalImageSha256VerifiedBeforeWrite",
    "bootedFromPhysicalUsb",
    "graphicalLiveSessionUsable",
    "internalDiskIdleUnchanged",
    "sourceUsbTargetRefused",
    "cancelLeavesTargetUnchanged",
    "wrongConfirmationLeavesTargetUnchanged",
    "targetAndPartitionPlanReviewed",
    "destructiveConfirmationBoundToTarget",
    "installedToDedicatedEmptyDisk",
    "sourceUsbPhysicallyDetachedBeforeInstalledBoot",
    "installedBootWithoutSourceUsb",
    "graphicalInstalledSessionUsable",
    "persistenceVerified",
    "graphicsVerified",
    "networkVerified",
    "audioVerified",
    "suspendResumeVerified",
    "firmwareInventoryReviewed",
    "noUserDataDiskUsed",
)


def fail(message: str) -> "NoReturn":
    raise SystemExit(f"physical qualification review failed: {message}")


def load_regular_json(path_text: str, max_bytes: int, label: str) -> dict[str, Any]:
    path = pathlib.Path(path_text)
    try:
        st = path.lstat()
    except OSError as exc:
        fail(f"cannot stat {label} file {path}: {exc}")
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode):
        fail(f"{label} input must be a regular non-symlink file: {path}")
    if st.st_size <= 0 or st.st_size > max_bytes:
        fail(f"{label} file size is outside the accepted range: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        fail(f"cannot parse {label} file {path}: {exc}")
    if not isinstance(data, dict):
        fail(f"{label} root must be an object")
    return data


def load_sequence_module() -> Any:
    path = pathlib.Path(__file__).with_name("verify-physical-live-usb-sequence.py")
    spec = importlib.util.spec_from_file_location("swir_physical_sequence", path)
    if spec is None or spec.loader is None:
        fail("cannot load physical sequence verifier")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def verify_review_digest(review: dict[str, Any]) -> None:
    actual = review.get("reviewDigestSha256")
    if not isinstance(actual, str) or not HEX64.fullmatch(actual):
        fail("reviewDigestSha256 is missing or invalid")
    unsigned = dict(review)
    unsigned.pop("reviewDigestSha256", None)
    canonical = json.dumps(unsigned, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    expected = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    if not hmac.compare_digest(actual, expected):
        fail("review digest mismatch")


def require_digest(value: Any, label: str) -> str:
    if not isinstance(value, str) or not HEX64.fullmatch(value):
        fail(f"{label} must be a lowercase SHA-256 hex digest")
    return value


def require_commit(value: Any) -> str:
    if not isinstance(value, str) or not HEX40.fullmatch(value):
        fail("sourceCommit must be a full lowercase 40-character Git commit SHA")
    return value


def parse_utc(value: Any) -> dt.datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        fail("reviewedAtUtc must be an RFC3339 UTC timestamp")
    try:
        parsed = dt.datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        fail(f"reviewedAtUtc is malformed: {exc}")
    if parsed.tzinfo is None:
        fail("reviewedAtUtc must include UTC timezone")
    return parsed


def evidence_digest(data: dict[str, Any], label: str) -> str:
    value = data.get("evidenceDigestSha256")
    return require_digest(value, f"{label} evidenceDigestSha256")


def verify_review(review: dict[str, Any], live: dict[str, Any], installed: dict[str, Any]) -> dict[str, Any]:
    if review.get("schema") != REVIEW_SCHEMA:
        fail("unexpected review schema")
    verify_review_digest(review)
    parse_utc(review.get("reviewedAtUtc"))

    source = review.get("sourceImage")
    if not isinstance(source, dict):
        fail("sourceImage must be an object")
    image_sha = require_digest(source.get("sha256"), "sourceImage.sha256")
    source_commit = require_commit(source.get("sourceCommit"))
    image_bytes = source.get("bytes")
    if not isinstance(image_bytes, int) or isinstance(image_bytes, bool) or image_bytes <= 0:
        fail("sourceImage.bytes must be a positive integer")

    binding = review.get("evidenceBinding")
    if not isinstance(binding, dict):
        fail("evidenceBinding must be an object")
    live_digest = evidence_digest(live, "live")
    installed_digest = evidence_digest(installed, "installed")
    if not hmac.compare_digest(require_digest(binding.get("liveEvidenceDigestSha256"), "evidenceBinding.liveEvidenceDigestSha256"), live_digest):
        fail("review is not bound to the supplied Live evidence")
    if not hmac.compare_digest(require_digest(binding.get("installedEvidenceDigestSha256"), "evidenceBinding.installedEvidenceDigestSha256"), installed_digest):
        fail("review is not bound to the supplied installed evidence")

    hardware_scope = review.get("hardwareScope")
    if not isinstance(hardware_scope, dict):
        fail("hardwareScope must be an object")
    scope_id = require_digest(hardware_scope.get("privacySafeIdSha256"), "hardwareScope.privacySafeIdSha256")
    if hardware_scope.get("serialsStored") is not False:
        fail("hardwareScope.serialsStored must remain false")

    observations = review.get("observations")
    if not isinstance(observations, dict):
        fail("observations must be an object")
    unknown = sorted(set(observations) - set(REQUIRED_OBSERVATIONS))
    if unknown:
        fail(f"unknown observation keys are not accepted: {', '.join(unknown)}")
    missing = [name for name in REQUIRED_OBSERVATIONS if observations.get(name) is not True]
    if missing:
        fail(f"required physical observations are not all confirmed: {', '.join(missing)}")

    claims = review.get("claims")
    if not isinstance(claims, dict):
        fail("claims must be an object")
    for key in ("secureBootSupportClaim", "legacyBiosSupportClaim", "allPcCompatibilityClaim"):
        if claims.get(key) is not False:
            fail(f"{key} must remain false for this qualification scope")

    sequence = load_sequence_module().verify_pair(live, installed)
    if sequence.get("passed") is not True or sequence.get("physicalHardwareRoadmapCompletionClaimed") is not False:
        fail("underlying physical sequence verification did not pass safely")

    return {
        "schema": "swir.physical-live-usb-review-verification/1.0",
        "passed": True,
        "reviewReady": True,
        "sourceImageSha256": image_sha,
        "sourceCommit": source_commit,
        "sourceImageBytes": image_bytes,
        "hardwareScopePrivacySafeIdSha256": scope_id,
        "liveEvidenceDigestSha256": live_digest,
        "installedEvidenceDigestSha256": installed_digest,
        "allRequiredPhysicalObservationsConfirmed": True,
        "sequenceVerificationPassed": True,
        "uefiOnly": True,
        "secureBootSupportClaim": False,
        "legacyBiosSupportClaim": False,
        "allPcCompatibilityClaim": False,
        "physicalHardwareRoadmapCompletionClaimed": False,
        "roadmapIntegrationDecisionRequired": True,
    }


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", required=True)
    parser.add_argument("--installed", required=True)
    parser.add_argument("--review", required=True)
    args = parser.parse_args(argv)

    sequence_module = load_sequence_module()
    live = sequence_module.load_regular_json(args.live)
    installed = sequence_module.load_regular_json(args.installed)
    review = load_regular_json(args.review, MAX_REVIEW_BYTES, "review")
    summary = verify_review(review, live, installed)
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
