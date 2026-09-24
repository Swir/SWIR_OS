#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import pathlib
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
VERIFY = HERE / "verify-physical-live-usb-review.py"
OBSERVATIONS = (
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


def finalize(payload: dict, field: str) -> dict:
    base = dict(payload)
    canonical = json.dumps(base, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    base[field] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return base


def evidence(phase: str, *, usb: bool, marker: str = "same-token") -> dict:
    dmi = {"sysVendor": "SWIR Test Lab", "productName": "Physical Fixture", "productVersion": "1"}
    transport = "usb" if usb else "nvme"
    payload = {
        "schema": "swir.physical-live-usb-evidence/1.0",
        "phase": phase,
        "capturedAtUtc": "2026-09-24T00:00:00Z" if phase == "live" else "2026-09-24T00:45:00Z",
        "collector": {"readOnly": True, "requiresRoot": False, "destructiveActions": False, "privacyMode": "serial-redacted"},
        "system": {
            "architecture": "x86_64", "kernel": "fixture", "bootMode": "uefi",
            "secureBootStateObserved": "disabled", "secureBootSupportClaim": False,
            "virtualization": "none", "virtualizationHeuristic": False, "dmi": dmi,
        },
        "root": {
            "source": "/dev/sdb2" if usb else "/dev/nvme0n1p2", "filesystem": "ext4",
            "leafLabel": "SWIR_LIVE_ROOT" if usb else "SWIR_ROOT", "parentTransport": transport,
            "sourceChain": [],
        },
        "blockDevices": [],
        "liveUsbEvidence": {
            "expectedRootLabel": "SWIR_LIVE_ROOT", "rootLabelMatches": usb,
            "rootParentTransportIsUsb": usb, "physicalCandidate": phase == "live" and usb,
        },
        "installedBootEvidence": {
            "rootParentTransportIsUsb": usb, "persistenceMarkerPresent": True,
            "persistenceMarkerSha256": hashlib.sha256(marker.encode()).hexdigest(),
            "installedCandidate": phase == "installed" and not usb,
        },
        "claims": {
            "physicalHardwareQualificationClaim": False, "secureBootSupportClaim": False,
            "legacyBiosSupportClaim": False, "allPcCompatibilityClaim": False,
        },
        "reviewRequired": [],
    }
    return finalize(payload, "evidenceDigestSha256")


def review(live: dict, installed: dict) -> dict:
    payload = {
        "schema": "swir.physical-live-usb-review/1.0",
        "reviewedAtUtc": "2026-09-24T01:00:00Z",
        "sourceImage": {
            "sha256": "a" * 64,
            "sourceCommit": "b" * 40,
            "bytes": 4294967296,
        },
        "hardwareScope": {
            "privacySafeIdSha256": "c" * 64,
            "serialsStored": False,
        },
        "evidenceBinding": {
            "liveEvidenceDigestSha256": live["evidenceDigestSha256"],
            "installedEvidenceDigestSha256": installed["evidenceDigestSha256"],
        },
        "observations": {name: True for name in OBSERVATIONS},
        "claims": {
            "secureBootSupportClaim": False,
            "legacyBiosSupportClaim": False,
            "allPcCompatibilityClaim": False,
        },
    }
    return finalize(payload, "reviewDigestSha256")


def invoke(live: dict, installed: dict, operator_review: dict) -> subprocess.CompletedProcess[str]:
    with tempfile.TemporaryDirectory() as temp:
        root = pathlib.Path(temp)
        live_path = root / "live.json"
        installed_path = root / "installed.json"
        review_path = root / "review.json"
        live_path.write_text(json.dumps(live), encoding="utf-8")
        installed_path.write_text(json.dumps(installed), encoding="utf-8")
        review_path.write_text(json.dumps(operator_review), encoding="utf-8")
        return subprocess.run(
            [sys.executable, str(VERIFY), "--live", str(live_path), "--installed", str(installed_path), "--review", str(review_path)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )


def refinalize(data: dict) -> dict:
    data = dict(data)
    data.pop("reviewDigestSha256", None)
    return finalize(data, "reviewDigestSha256")


def main() -> int:
    live = evidence("live", usb=True)
    installed = evidence("installed", usb=False)
    good_review = review(live, installed)
    good = invoke(live, installed, good_review)
    assert good.returncode == 0, good.stderr
    summary = json.loads(good.stdout)
    assert summary["passed"] is True
    assert summary["reviewReady"] is True
    assert summary["allRequiredPhysicalObservationsConfirmed"] is True
    assert summary["physicalHardwareRoadmapCompletionClaimed"] is False

    missing_observation = json.loads(json.dumps(good_review))
    missing_observation["observations"]["sourceUsbTargetRefused"] = False
    missing_observation = refinalize(missing_observation)
    refused = invoke(live, installed, missing_observation)
    assert refused.returncode != 0
    assert "sourceUsbTargetRefused" in refused.stderr

    wrong_binding = json.loads(json.dumps(good_review))
    wrong_binding["evidenceBinding"]["liveEvidenceDigestSha256"] = "d" * 64
    wrong_binding = refinalize(wrong_binding)
    binding_result = invoke(live, installed, wrong_binding)
    assert binding_result.returncode != 0
    assert "not bound" in binding_result.stderr

    bad_image = json.loads(json.dumps(good_review))
    bad_image["sourceImage"]["sha256"] = "NOT-A-SHA"
    bad_image = refinalize(bad_image)
    image_result = invoke(live, installed, bad_image)
    assert image_result.returncode != 0
    assert "sourceImage.sha256" in image_result.stderr

    overclaim = json.loads(json.dumps(good_review))
    overclaim["claims"]["secureBootSupportClaim"] = True
    overclaim = refinalize(overclaim)
    claim_result = invoke(live, installed, overclaim)
    assert claim_result.returncode != 0
    assert "secureBootSupportClaim" in claim_result.stderr

    tampered = json.loads(json.dumps(good_review))
    tampered["sourceImage"]["bytes"] += 1
    tamper_result = invoke(live, installed, tampered)
    assert tamper_result.returncode != 0
    assert "review digest mismatch" in tamper_result.stderr

    print(json.dumps({
        "schema": "swir.physical-live-usb-review-selftest/1.0",
        "passed": True,
        "validReviewAccepted": True,
        "missingObservationRejected": True,
        "crossEvidenceBindingRejected": True,
        "malformedImageProvenanceRejected": True,
        "unsupportedClaimRejected": True,
        "tamperRejected": True,
        "roadmapCompletionClaimed": False,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
