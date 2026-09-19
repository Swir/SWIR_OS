#!/usr/bin/env python3
from __future__ import annotations

import os
import pathlib
import tempfile
from unittest import mock

from hardware_center_runtime import (
    HardwareCenterError,
    MAX_DEVICE_ROWS,
    MAX_FIRMWARE_ROWS,
    _report_script,
    parse_driver_center_report,
)


def sample_firmware_update(index: int = 1) -> dict:
    return {
        "deviceId": f"fixture-device-{index:04d}",
        "deviceName": "System Firmware",
        "currentVersion": "1.0.0",
        "version": "1.2.0",
        "releaseId": f"lvfs-release-{index}",
        "remoteId": "lvfs",
        "checksums": ["a" * 64],
        "requiresReboot": True,
        "source": {
            "class": "fwupd-lvfs",
            "repositoryId": "lvfs",
            "ref": f"fwupd:fixture-device-{index:04d}:lvfs-release-{index}",
        },
        "trustedSource": True,
        "directDownloadUrlExposed": False,
        "mutationAuthorized": False,
    }


def sample_report() -> dict:
    return {
        "schema": "swir.driver-center-report/0.1",
        "readOnly": True,
        "autoMutation": False,
        "host": {
            "kernel": "6.12.0-test",
            "distribution": {"id": "debian", "prettyName": "Debian GNU/Linux 13"},
            "capabilities": {"fwupd": {"available": True, "lvfsMetadataPresent": True}},
        },
        "summary": {
            "devices": 2,
            "healthy": 1,
            "attention": 1,
            "unknown": 0,
            "operations": 1,
            "violations": 0,
        },
        "devices": [
            {
                "key": "pci:0000:00:1f.6",
                "bus": "pci",
                "ids": {"vendor": "8086", "device": "15f3"},
                "status": "healthy",
                "driver": {"status": "loaded", "module": "e1000e"},
                "catalog": {"entryIds": ["pci.intel.i219-v-15f3"]},
            },
            {
                "key": "usb:1-1",
                "bus": "usb",
                "ids": {"vendor": "046d", "product": "c534"},
                "status": "attention",
                "driver": {"status": "unbound", "module": None},
                "catalog": {"entryIds": ["usb.logitech.receiver.c534"]},
            },
        ],
        "operations": [
            {
                "id": "usb:1-1:review-module:1",
                "deviceKey": "usb:1-1",
                "kind": "review-module",
                "reason": "Review kernel module candidates.",
                "requiresPrivilege": True,
                "sources": [{"class": "kernel-in-tree", "ref": "linux:drivers/hid"}],
            }
        ],
        "firmware": {
            "provider": "fwupd-lvfs",
            "readOnly": True,
            "mutationAuthorized": False,
            "available": True,
            "binaryTrusted": True,
            "inventoryReady": True,
            "updates": [sample_firmware_update()],
            "ignoredNonLvfsCandidates": 0,
            "errorCode": None,
        },
        "violations": [],
    }


def expect_error(mutator) -> None:
    payload = sample_report()
    mutator(payload)
    try:
        parse_driver_center_report(payload)
    except HardwareCenterError:
        return
    raise AssertionError("unsafe report was accepted")


report = parse_driver_center_report(sample_report())
assert report.distribution == "Debian GNU/Linux 13"
assert report.kernel == "6.12.0-test"
assert report.fwupd_available is True and report.lvfs_metadata_present is True
assert report.firmware_inventory_ready is True and report.firmware_error_code == ""
assert report.devices_total == 2 and len(report.devices) == 2
assert report.devices[0].module == "e1000e"
assert report.operations_total == 1 and report.operations[0].privilege_required is True
assert report.operations[0].source_classes == "kernel-in-tree"
assert len(report.firmware_updates) == 1
assert report.firmware_updates[0].target_version == "1.2.0"
assert report.firmware_updates[0].requires_reboot is True
assert report.firmware_updates[0].source_ref.startswith("fwupd:")
assert report.firmware_updates[0].checksum_count == 1

expect_error(lambda payload: payload.__setitem__("schema", "wrong"))
expect_error(lambda payload: payload.__setitem__("readOnly", False))
expect_error(lambda payload: payload.__setitem__("autoMutation", True))
expect_error(lambda payload: payload["violations"].append({"code": "UNSAFE"}))
expect_error(lambda payload: payload["summary"].__setitem__("devices", -1))
expect_error(lambda payload: payload["firmware"].__setitem__("readOnly", False))
expect_error(lambda payload: payload["firmware"].__setitem__("mutationAuthorized", True))
expect_error(lambda payload: payload["firmware"]["updates"][0].__setitem__("remoteId", "vendor"))
expect_error(lambda payload: payload["firmware"]["updates"][0].__setitem__("directDownloadUrlExposed", True))
expect_error(lambda payload: payload["firmware"]["updates"][0]["source"].__setitem__("ref", "https://example.invalid/firmware.bin"))

bounded = sample_report()
bounded["devices"] = bounded["devices"] * (MAX_DEVICE_ROWS + 5)
parsed = parse_driver_center_report(bounded)
assert len(parsed.devices) == MAX_DEVICE_ROWS

firmware_bounded = sample_report()
firmware_bounded["firmware"]["updates"] = [sample_firmware_update(index) for index in range(MAX_FIRMWARE_ROWS + 7)]
parsed = parse_driver_center_report(firmware_bounded)
assert len(parsed.firmware_updates) == MAX_FIRMWARE_ROWS

with tempfile.TemporaryDirectory() as td:
    script = pathlib.Path(td) / "report.mjs"
    script.write_text("console.log('{}')\n", encoding="utf-8")
    with mock.patch.dict(
        os.environ,
        {
            "SWIR_APP_E2E": "1",
            "SWIR_HARDWARE_CENTER_REPORT_SCRIPT": str(script),
        },
        clear=False,
    ):
        assert _report_script() == script

print("hardware_center_runtime self-test: OK")
