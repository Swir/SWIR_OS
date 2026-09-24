#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import pathlib
import stat
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
CREATE = HERE / "new-physical-live-usb-review.py"
VERIFY = HERE / "verify-physical-live-usb-review.py"
OBS = (
    "finalImageSha256VerifiedBeforeWrite", "bootedFromPhysicalUsb", "graphicalLiveSessionUsable",
    "internalDiskIdleUnchanged", "sourceUsbTargetRefused", "cancelLeavesTargetUnchanged",
    "wrongConfirmationLeavesTargetUnchanged", "targetAndPartitionPlanReviewed",
    "destructiveConfirmationBoundToTarget", "installedToDedicatedEmptyDisk",
    "sourceUsbPhysicallyDetachedBeforeInstalledBoot", "installedBootWithoutSourceUsb",
    "graphicalInstalledSessionUsable", "persistenceVerified", "graphicsVerified", "networkVerified",
    "audioVerified", "suspendResumeVerified", "firmwareInventoryReviewed", "noUserDataDiskUsed",
)


def finalize(payload: dict) -> dict:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    payload = dict(payload)
    payload["evidenceDigestSha256"] = hashlib.sha256(canonical.encode()).hexdigest()
    return payload


def evidence(phase: str, usb: bool) -> dict:
    marker = hashlib.sha256(b"token").hexdigest()
    payload = {
        "schema": "swir.physical-live-usb-evidence/1.0", "phase": phase,
        "capturedAtUtc": "2026-09-24T00:00:00Z" if phase == "live" else "2026-09-24T00:45:00Z",
        "collector": {"readOnly": True, "requiresRoot": False, "destructiveActions": False, "privacyMode": "serial-redacted"},
        "system": {"architecture": "x86_64", "kernel": "fixture", "bootMode": "uefi", "secureBootStateObserved": "disabled", "secureBootSupportClaim": False, "virtualization": "none", "virtualizationHeuristic": False, "dmi": {"sysVendor": "SWIR Test Lab", "productName": "Physical Fixture", "productVersion": "1"}},
        "root": {"source": "/dev/sdb2" if usb else "/dev/nvme0n1p2", "filesystem": "ext4", "leafLabel": "SWIR_LIVE_ROOT" if usb else "SWIR_ROOT", "parentTransport": "usb" if usb else "nvme", "sourceChain": []},
        "blockDevices": [],
        "liveUsbEvidence": {"expectedRootLabel": "SWIR_LIVE_ROOT", "rootLabelMatches": usb, "rootParentTransportIsUsb": usb, "physicalCandidate": phase == "live" and usb},
        "installedBootEvidence": {"rootParentTransportIsUsb": usb, "persistenceMarkerPresent": True, "persistenceMarkerSha256": marker, "installedCandidate": phase == "installed" and not usb},
        "claims": {"physicalHardwareQualificationClaim": False, "secureBootSupportClaim": False, "legacyBiosSupportClaim": False, "allPcCompatibilityClaim": False},
        "reviewRequired": [],
    }
    return finalize(payload)


def main() -> int:
    with tempfile.TemporaryDirectory() as temp:
        root = pathlib.Path(temp)
        live_path, installed_path = root / "live.json", root / "installed.json"
        observations_path, output_path = root / "observations.json", root / "review.json"
        live_path.write_text(json.dumps(evidence("live", True)), encoding="utf-8")
        installed_path.write_text(json.dumps(evidence("installed", False)), encoding="utf-8")
        observations_path.write_text(json.dumps({name: True for name in OBS}), encoding="utf-8")
        scope = "Dedicated lab laptop #fixture-only"
        result = subprocess.run([
            sys.executable, str(CREATE), "--live", str(live_path), "--installed", str(installed_path),
            "--observations", str(observations_path), "--image-sha256", "a" * 64,
            "--source-commit", "b" * 40, "--image-bytes", "4294967296",
            "--hardware-scope", scope, "--output", str(output_path)
        ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        assert result.returncode == 0, result.stderr
        assert stat.S_IMODE(output_path.stat().st_mode) == 0o600
        review = json.loads(output_path.read_text(encoding="utf-8"))
        assert review["hardwareScope"]["privacySafeIdSha256"] == hashlib.sha256(scope.encode()).hexdigest()
        assert scope not in output_path.read_text(encoding="utf-8")
        verify = subprocess.run([sys.executable, str(VERIFY), "--live", str(live_path), "--installed", str(installed_path), "--review", str(output_path)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        assert verify.returncode == 0, verify.stderr
        assert json.loads(verify.stdout)["reviewReady"] is True
        repeat = subprocess.run([
            sys.executable, str(CREATE), "--live", str(live_path), "--installed", str(installed_path),
            "--observations", str(observations_path), "--image-sha256", "a" * 64,
            "--source-commit", "b" * 40, "--image-bytes", "4294967296",
            "--hardware-scope", scope, "--output", str(output_path)
        ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        assert repeat.returncode != 0 and "refusing to overwrite" in repeat.stderr

        incomplete = root / "incomplete.json"
        incomplete.write_text(json.dumps({name: (name != "audioVerified") for name in OBS}), encoding="utf-8")
        refused_output = root / "refused.json"
        refused = subprocess.run([
            sys.executable, str(CREATE), "--live", str(live_path), "--installed", str(installed_path),
            "--observations", str(incomplete), "--image-sha256", "a" * 64,
            "--source-commit", "b" * 40, "--image-bytes", "4294967296",
            "--hardware-scope", scope, "--output", str(refused_output)
        ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        assert refused.returncode != 0 and "audioVerified" in refused.stderr
        assert not refused_output.exists()

    print(json.dumps({
        "schema": "swir.physical-live-usb-review-creator-selftest/1.0",
        "passed": True,
        "exclusive0600OutputVerified": True,
        "rawHardwareScopeRedactionVerified": True,
        "incompleteObservationRefused": True,
        "generatedReviewVerified": True,
        "roadmapCompletionClaimed": False,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
