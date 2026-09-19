#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import pathlib
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
VERIFY = HERE / "verify-physical-live-usb-sequence.py"


def finalize(payload: dict) -> dict:
    base = dict(payload)
    canonical = json.dumps(base, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    base["evidenceDigestSha256"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return base


def evidence(phase: str, *, usb: bool, virtual: bool = False, marker: str | None = "same-token") -> dict:
    dmi = {"sysVendor": "SWIR Test Lab", "productName": "Physical Fixture", "productVersion": "1"}
    transport = "usb" if usb else "nvme"
    payload = {
        "schema": "swir.physical-live-usb-evidence/1.0",
        "phase": phase,
        "capturedAtUtc": "2026-09-19T05:00:00Z" if phase == "live" else "2026-09-19T05:30:00Z",
        "collector": {"readOnly": True, "requiresRoot": False, "destructiveActions": False, "privacyMode": "serial-redacted"},
        "system": {
            "architecture": "x86_64",
            "kernel": "fixture",
            "bootMode": "uefi",
            "secureBootStateObserved": "disabled",
            "secureBootSupportClaim": False,
            "virtualization": "kvm" if virtual else "none",
            "virtualizationHeuristic": virtual,
            "dmi": dmi,
        },
        "root": {
            "source": "/dev/sdb2" if usb else "/dev/nvme0n1p2",
            "filesystem": "ext4",
            "leafLabel": "SWIR_LIVE_ROOT" if usb else "SWIR_ROOT",
            "parentTransport": transport,
            "sourceChain": [],
        },
        "blockDevices": [],
        "liveUsbEvidence": {
            "expectedRootLabel": "SWIR_LIVE_ROOT",
            "rootLabelMatches": usb,
            "rootParentTransportIsUsb": usb,
            "physicalCandidate": phase == "live" and usb and not virtual,
        },
        "installedBootEvidence": {
            "rootParentTransportIsUsb": usb,
            "persistenceMarkerPresent": bool(marker),
            "persistenceMarkerSha256": hashlib.sha256(marker.encode()).hexdigest() if marker else None,
            "installedCandidate": phase == "installed" and not usb and not virtual and bool(marker),
        },
        "claims": {
            "physicalHardwareQualificationClaim": False,
            "secureBootSupportClaim": False,
            "legacyBiosSupportClaim": False,
            "allPcCompatibilityClaim": False,
        },
        "reviewRequired": [],
    }
    return finalize(payload)


def invoke(live: dict, installed: dict) -> subprocess.CompletedProcess[str]:
    with tempfile.TemporaryDirectory() as temp:
        root = pathlib.Path(temp)
        live_path = root / "live.json"
        installed_path = root / "installed.json"
        live_path.write_text(json.dumps(live), encoding="utf-8")
        installed_path.write_text(json.dumps(installed), encoding="utf-8")
        return subprocess.run(
            [sys.executable, str(VERIFY), "--live", str(live_path), "--installed", str(installed_path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )


def main() -> int:
    good = invoke(evidence("live", usb=True), evidence("installed", usb=False))
    assert good.returncode == 0, good.stderr
    summary = json.loads(good.stdout)
    assert summary["passed"] is True
    assert summary["physicalHardwareRoadmapCompletionClaimed"] is False

    virtual = invoke(evidence("live", usb=True, virtual=True), evidence("installed", usb=False))
    assert virtual.returncode != 0

    same_usb = invoke(evidence("live", usb=True), evidence("installed", usb=True))
    assert same_usb.returncode != 0

    marker_mismatch = invoke(evidence("live", usb=True, marker="A"), evidence("installed", usb=False, marker="B"))
    assert marker_mismatch.returncode != 0

    tampered_live = evidence("live", usb=True)
    tampered_live["system"]["architecture"] = "tampered"
    tampered = invoke(tampered_live, evidence("installed", usb=False))
    assert tampered.returncode != 0
    assert "digest mismatch" in tampered.stderr

    print(json.dumps({
        "schema": "swir.physical-live-usb-sequence-selftest/1.0",
        "passed": True,
        "validSequenceAccepted": True,
        "virtualEvidenceRejected": True,
        "sourceUsbStillAttachedRejected": True,
        "persistenceMismatchRejected": True,
        "tamperRejected": True,
        "roadmapCompletionClaimed": False,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
