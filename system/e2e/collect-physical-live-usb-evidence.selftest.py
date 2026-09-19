#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import stat
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
COLLECTOR = HERE / "collect-physical-live-usb-evidence.py"


def run(fixture: dict, phase: str, extra: list[str] | None = None) -> dict:
    with tempfile.TemporaryDirectory() as temp:
        fixture_path = pathlib.Path(temp) / "fixture.json"
        fixture_path.write_text(json.dumps(fixture), encoding="utf-8")
        command = [sys.executable, str(COLLECTOR), "--phase", phase, "--fixture", str(fixture_path)]
        if extra:
            command.extend(extra)
        result = subprocess.run(command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        return json.loads(result.stdout)


def base_fixture(transport: str = "usb", virtual: str = "none", label: str = "SWIR_LIVE_ROOT") -> dict:
    return {
        "bootMode": "uefi",
        "secureBootState": "disabled",
        "virtualization": virtual,
        "kernel": "6.12.0-test",
        "architecture": "x86_64",
        "dmi": {"sysVendor": "SWIR Test Lab", "productName": "Bare Metal Fixture", "productVersion": "1"},
        "findmnt": {"filesystems": [{"source": "/dev/sdb2", "fstype": "ext4", "target": "/"}]},
        "lsblk": {
            "blockdevices": [
                {
                    "name": "/dev/sdb",
                    "kname": "sdb",
                    "type": "disk",
                    "tran": transport,
                    "rm": 1 if transport == "usb" else 0,
                    "ro": 0,
                    "size": "32000000000",
                    "fstype": None,
                    "label": None,
                    "mountpoints": [],
                    "model": "Fixture Disk",
                    "serial": "REDACT-ME",
                    "children": [
                        {
                            "name": "/dev/sdb2",
                            "kname": "sdb2",
                            "pkname": "sdb",
                            "type": "part",
                            "tran": None,
                            "rm": 1 if transport == "usb" else 0,
                            "ro": 0,
                            "size": "30000000000",
                            "fstype": "ext4",
                            "label": label,
                            "mountpoints": ["/"],
                            "model": "",
                            "serial": "",
                        }
                    ],
                }
            ]
        },
    }


def verify_digest(data: dict) -> None:
    digest = data.pop("evidenceDigestSha256")
    canonical = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    expected = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    assert digest == expected
    data["evidenceDigestSha256"] = digest


def main() -> int:
    live = run(base_fixture(), "live")
    assert live["schema"] == "swir.physical-live-usb-evidence/1.0"
    assert live["collector"]["readOnly"] is True
    assert live["collector"]["requiresRoot"] is False
    assert live["collector"]["destructiveActions"] is False
    assert live["claims"]["physicalHardwareQualificationClaim"] is False
    assert live["claims"]["secureBootSupportClaim"] is False
    assert live["liveUsbEvidence"]["rootLabelMatches"] is True
    assert live["liveUsbEvidence"]["rootParentTransportIsUsb"] is True
    assert live["liveUsbEvidence"]["physicalCandidate"] is True
    assert live["blockDevices"][0]["serialPresent"] is True
    assert "REDACT-ME" not in json.dumps(live)
    verify_digest(live)

    vm_fixture = base_fixture()
    vm_fixture["virtualization"] = "kvm"
    vm = run(vm_fixture, "live")
    assert vm["system"]["virtualizationHeuristic"] is True
    assert vm["liveUsbEvidence"]["physicalCandidate"] is False

    wrong_label = run(base_fixture(label="NOT_SWIR"), "live")
    assert wrong_label["liveUsbEvidence"]["physicalCandidate"] is False

    installed_fixture = base_fixture(transport="nvme", label="SWIR_ROOT")
    installed_fixture["persistenceMarker"] = "physical-test-token"
    installed = run(installed_fixture, "installed")
    assert installed["installedBootEvidence"]["rootParentTransportIsUsb"] is False
    assert installed["installedBootEvidence"]["persistenceMarkerPresent"] is True
    assert installed["installedBootEvidence"]["installedCandidate"] is True
    assert installed["claims"]["physicalHardwareQualificationClaim"] is False

    no_persistence = base_fixture(transport="nvme", label="SWIR_ROOT")
    installed_missing = run(no_persistence, "installed")
    assert installed_missing["installedBootEvidence"]["installedCandidate"] is False

    with tempfile.TemporaryDirectory() as temp:
        fixture_path = pathlib.Path(temp) / "fixture.json"
        fixture_path.write_text(json.dumps(base_fixture()), encoding="utf-8")
        output = pathlib.Path(temp) / "evidence.json"
        subprocess.run(
            [sys.executable, str(COLLECTOR), "--phase", "live", "--fixture", str(fixture_path), "--output", str(output)],
            check=True,
        )
        assert stat.S_IMODE(output.stat().st_mode) == 0o600
        second = subprocess.run(
            [sys.executable, str(COLLECTOR), "--phase", "live", "--fixture", str(fixture_path), "--output", str(output)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        assert second.returncode != 0
        assert "refusing to overwrite" in second.stderr

    print(json.dumps({
        "schema": "swir.physical-live-usb-evidence-selftest/1.0",
        "passed": True,
        "liveUsbCandidateFixture": True,
        "virtualizationRefusalFixture": True,
        "installedDetachedBootFixture": True,
        "serialRedactionVerified": True,
        "exclusive0600OutputVerified": True,
        "qualificationClaimed": False,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
