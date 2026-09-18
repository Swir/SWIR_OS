#!/usr/bin/env python3
"""Read-only adapter from native GTK apps to SWIR Driver Center diagnostics."""

from __future__ import annotations

import json
import os
import pathlib
import subprocess
from dataclasses import dataclass
from typing import Any, Final

NODE: Final = pathlib.Path("/usr/bin/node")
PRODUCTION_REPORT: Final = pathlib.Path("/usr/local/lib/swir/hardware/driver-center-report.mjs")
QUERY_TIMEOUT_SECONDS: Final = 6
MAX_OUTPUT_BYTES: Final = 1024 * 1024
MAX_DEVICE_ROWS: Final = 256
MAX_OPERATION_ROWS: Final = 256


class HardwareCenterError(RuntimeError):
    """Raised when the diagnostic report cannot be trusted or consumed safely."""


@dataclass(frozen=True)
class HardwareDevice:
    key: str
    bus: str
    status: str
    driver_status: str
    module: str
    ids: str
    catalog_entries: str


@dataclass(frozen=True)
class HardwareOperation:
    operation_id: str
    device_key: str
    kind: str
    reason: str
    privilege_required: bool
    source_classes: str


@dataclass(frozen=True)
class HardwareReport:
    distribution: str
    kernel: str
    fwupd_available: bool
    lvfs_metadata_present: bool
    devices_total: int
    healthy: int
    attention: int
    unknown: int
    operations_total: int
    devices: tuple[HardwareDevice, ...]
    operations: tuple[HardwareOperation, ...]


def _text(value: Any, limit: int = 240) -> str:
    if value is None:
        return ""
    return str(value).replace("\x00", "").strip()[:limit]


def _bounded_int(value: Any, *, maximum: int = 1_000_000) -> int:
    if isinstance(value, bool):
        return int(value)
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise HardwareCenterError(f"invalid numeric report field: {value!r}") from exc
    if result < 0 or result > maximum:
        raise HardwareCenterError(f"numeric report field outside safe bounds: {result}")
    return result


def _format_ids(ids: Any) -> str:
    if not isinstance(ids, dict):
        return ""
    pairs = []
    for key in ("vendor", "device", "product", "subsystemVendor", "subsystemDevice"):
        value = _text(ids.get(key), 32)
        if value:
            pairs.append(f"{key}={value}")
    return " ".join(pairs)[:240]


def parse_driver_center_report(payload: Any) -> HardwareReport:
    if not isinstance(payload, dict):
        raise HardwareCenterError("Driver Center report must be an object")
    if payload.get("schema") != "swir.driver-center-report/0.1":
        raise HardwareCenterError("unsupported Driver Center report schema")
    if payload.get("readOnly") is not True or payload.get("autoMutation") is not False:
        raise HardwareCenterError("Driver Center report violated read-only policy")
    violations = payload.get("violations")
    if not isinstance(violations, list) or violations:
        raise HardwareCenterError("Driver Center report contains policy violations")

    host = payload.get("host")
    summary = payload.get("summary")
    if not isinstance(host, dict) or not isinstance(summary, dict):
        raise HardwareCenterError("Driver Center report is missing host/summary data")

    distro = host.get("distribution") if isinstance(host.get("distribution"), dict) else {}
    capabilities = host.get("capabilities") if isinstance(host.get("capabilities"), dict) else {}
    fwupd = capabilities.get("fwupd") if isinstance(capabilities.get("fwupd"), dict) else {}

    raw_devices = payload.get("devices")
    raw_operations = payload.get("operations")
    if not isinstance(raw_devices, list) or not isinstance(raw_operations, list):
        raise HardwareCenterError("Driver Center report is missing device/operation arrays")
    if len(raw_devices) > MAX_DEVICE_ROWS:
        raw_devices = raw_devices[:MAX_DEVICE_ROWS]
    if len(raw_operations) > MAX_OPERATION_ROWS:
        raw_operations = raw_operations[:MAX_OPERATION_ROWS]

    devices: list[HardwareDevice] = []
    for item in raw_devices:
        if not isinstance(item, dict):
            continue
        driver = item.get("driver") if isinstance(item.get("driver"), dict) else {}
        catalog = item.get("catalog") if isinstance(item.get("catalog"), dict) else {}
        entries = catalog.get("entryIds") if isinstance(catalog.get("entryIds"), list) else []
        devices.append(
            HardwareDevice(
                key=_text(item.get("key"), 160) or "unknown-device",
                bus=_text(item.get("bus"), 32) or "unknown",
                status=_text(item.get("status"), 32) or "unknown",
                driver_status=_text(driver.get("status"), 32) or "unknown",
                module=_text(driver.get("module"), 96) or "—",
                ids=_format_ids(item.get("ids")),
                catalog_entries=", ".join(_text(value, 96) for value in entries[:8])[:320] or "—",
            )
        )

    operations: list[HardwareOperation] = []
    for item in raw_operations:
        if not isinstance(item, dict):
            continue
        sources = item.get("sources") if isinstance(item.get("sources"), list) else []
        source_classes = sorted({
            _text(source.get("class"), 64)
            for source in sources
            if isinstance(source, dict) and _text(source.get("class"), 64)
        })
        operations.append(
            HardwareOperation(
                operation_id=_text(item.get("id"), 180) or "unknown-operation",
                device_key=_text(item.get("deviceKey"), 160) or "unknown-device",
                kind=_text(item.get("kind"), 80) or "review",
                reason=_text(item.get("reason"), 500),
                privilege_required=item.get("requiresPrivilege") is True,
                source_classes=", ".join(source_classes)[:240] or "diagnostic",
            )
        )

    return HardwareReport(
        distribution=_text(distro.get("prettyName"), 160) or _text(distro.get("id"), 80) or "Unknown Linux",
        kernel=_text(host.get("kernel"), 160) or "unknown",
        fwupd_available=fwupd.get("available") is True,
        lvfs_metadata_present=fwupd.get("lvfsMetadataPresent") is True,
        devices_total=_bounded_int(summary.get("devices", len(devices))),
        healthy=_bounded_int(summary.get("healthy", 0)),
        attention=_bounded_int(summary.get("attention", 0)),
        unknown=_bounded_int(summary.get("unknown", 0)),
        operations_total=_bounded_int(summary.get("operations", len(operations))),
        devices=tuple(devices),
        operations=tuple(operations),
    )


def _report_script() -> pathlib.Path:
    if os.environ.get("SWIR_APP_E2E") == "1":
        override = os.environ.get("SWIR_HARDWARE_CENTER_REPORT_SCRIPT", "")
        if override:
            candidate = pathlib.Path(override)
            if not candidate.is_absolute() or not candidate.is_file() or candidate.is_symlink():
                raise HardwareCenterError("invalid E2E Driver Center report script override")
            return candidate
    return PRODUCTION_REPORT


def read_hardware_report() -> HardwareReport:
    script = _report_script()
    if not NODE.is_file() or not os.access(NODE, os.X_OK):
        raise HardwareCenterError("trusted /usr/bin/node runtime is unavailable")
    if not script.is_file() or script.is_symlink():
        raise HardwareCenterError("trusted Driver Center report runtime is unavailable")

    try:
        completed = subprocess.run(
            (str(NODE), str(script), "--compact"),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
            close_fds=True,
            check=False,
            timeout=QUERY_TIMEOUT_SECONDS,
            env={**os.environ, "LC_ALL": "C"},
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise HardwareCenterError(f"Driver Center diagnostics failed: {exc}") from exc

    if len(completed.stdout) > MAX_OUTPUT_BYTES or len(completed.stderr) > MAX_OUTPUT_BYTES:
        raise HardwareCenterError("Driver Center diagnostics exceeded output bounds")
    if completed.returncode != 0:
        error = completed.stderr.decode("utf-8", "replace").strip()
        raise HardwareCenterError((error or f"Driver Center exited with {completed.returncode}")[:500])

    try:
        payload = json.loads(completed.stdout.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HardwareCenterError("Driver Center emitted invalid JSON") from exc
    return parse_driver_center_report(payload)
