#!/usr/bin/env python3
"""Read-only evidence collector for physical SWIR OS Live USB qualification.

This tool never formats disks, changes mount state, enables Secure Boot, installs
packages, or claims hardware qualification. It collects a privacy-minimized,
tamper-evident snapshot that can be reviewed together with the physical test
procedure.
"""
from __future__ import annotations

import argparse
import datetime as dt
import glob
import hashlib
import json
import os
import pathlib
import platform
import re
import subprocess
import sys
from typing import Any, Final

SCHEMA: Final = "swir.physical-live-usb-evidence/1.0"
LIVE_ROOT_LABEL: Final = "SWIR_LIVE_ROOT"
PERSISTENCE_MARKER: Final = pathlib.Path("/var/lib/swir/qualification/persistence-token")
DMI_PATHS: Final = {
    "sysVendor": pathlib.Path("/sys/class/dmi/id/sys_vendor"),
    "productName": pathlib.Path("/sys/class/dmi/id/product_name"),
    "productVersion": pathlib.Path("/sys/class/dmi/id/product_version"),
}
VIRTUAL_MARKERS: Final = (
    "qemu", "kvm", "virtualbox", "vmware", "hyper-v", "microsoft corporation",
    "xen", "bochs", "parallels", "bhyve",
)


def fail(message: str, code: int = 2) -> "NoReturn":
    raise SystemExit(f"physical evidence collection failed: {message}")


def read_text(path: pathlib.Path, limit: int = 4096) -> str | None:
    try:
        raw = path.read_bytes()
    except (FileNotFoundError, PermissionError, OSError):
        return None
    if len(raw) > limit:
        raw = raw[:limit]
    return raw.decode("utf-8", errors="replace").strip()


def run_json(argv: list[str]) -> dict[str, Any]:
    try:
        result = subprocess.run(
            argv,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=10,
        )
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        fail(f"required read-only probe failed: {argv[0]}: {exc}")
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        fail(f"probe returned malformed JSON: {argv[0]}: {exc}")
    if not isinstance(data, dict):
        fail(f"probe returned unexpected JSON root: {argv[0]}")
    return data


def normalize_lsblk(data: dict[str, Any]) -> list[dict[str, Any]]:
    raw = data.get("blockdevices")
    if not isinstance(raw, list):
        fail("lsblk fixture/probe lacks blockdevices array")
    flat: list[dict[str, Any]] = []

    def walk(node: Any, inherited_parent: str | None = None) -> None:
        if not isinstance(node, dict):
            fail("lsblk contains a non-object block device")
        item = dict(node)
        children = item.pop("children", None)
        if inherited_parent and not item.get("pkname"):
            item["pkname"] = inherited_parent
        flat.append(item)
        if children is not None:
            if not isinstance(children, list):
                fail("lsblk children is not an array")
            parent = str(item.get("kname") or "").strip() or None
            for child in children:
                walk(child, parent)

    for node in raw:
        walk(node)
    return flat


def first_mount_source(findmnt: dict[str, Any]) -> tuple[str | None, str | None]:
    filesystems = findmnt.get("filesystems")
    if not isinstance(filesystems, list) or not filesystems:
        return None, None
    row = filesystems[0]
    if not isinstance(row, dict):
        return None, None
    source = row.get("source")
    fstype = row.get("fstype")
    return (str(source) if source else None, str(fstype) if fstype else None)


def device_index(devices: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for dev in devices:
        for key in ("name", "kname"):
            value = dev.get(key)
            if value:
                text = str(value)
                result[text] = dev
                result[pathlib.Path(text).name] = dev
    return result


def root_device_chain(source: str | None, devices: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not source or not source.startswith("/dev/"):
        return []
    idx = device_index(devices)
    current = idx.get(source) or idx.get(pathlib.Path(source).name)
    chain: list[dict[str, Any]] = []
    seen: set[str] = set()
    while current:
        kname = str(current.get("kname") or current.get("name") or "")
        if not kname or kname in seen:
            break
        seen.add(kname)
        chain.append(current)
        parent = current.get("pkname")
        if not parent:
            break
        current = idx.get(str(parent)) or idx.get(pathlib.Path(str(parent)).name)
    return chain


def safe_device_summary(dev: dict[str, Any]) -> dict[str, Any]:
    # Serial numbers, WWNs, hostnames, MACs and user identity are deliberately
    # excluded from the default evidence bundle.
    mountpoints = dev.get("mountpoints")
    if not isinstance(mountpoints, list):
        mountpoints = [dev.get("mountpoint")] if dev.get("mountpoint") else []
    return {
        "name": str(dev.get("name") or ""),
        "kname": str(dev.get("kname") or ""),
        "pkname": str(dev.get("pkname") or ""),
        "type": str(dev.get("type") or ""),
        "transport": str(dev.get("tran") or ""),
        "removable": bool(dev.get("rm") in (1, True, "1", "true", "True")),
        "readOnly": bool(dev.get("ro") in (1, True, "1", "true", "True")),
        "size": str(dev.get("size") or ""),
        "filesystem": str(dev.get("fstype") or ""),
        "label": str(dev.get("label") or ""),
        "mountpoints": [str(x) for x in mountpoints if x],
        "model": str(dev.get("model") or "").strip()[:160],
        "serialPresent": bool(str(dev.get("serial") or "").strip()),
    }


def secure_boot_state() -> str:
    matches = glob.glob("/sys/firmware/efi/efivars/SecureBoot-*")
    if not matches:
        return "unknown"
    try:
        raw = pathlib.Path(matches[0]).read_bytes()
    except (PermissionError, OSError):
        return "unknown"
    # efivarfs prepends four bytes of attributes; the payload byte is 0/1.
    if len(raw) >= 5:
        if raw[4] == 1:
            return "enabled"
        if raw[4] == 0:
            return "disabled"
    return "unknown"


def looks_virtual(dmi: dict[str, str | None], virt: str | None) -> bool:
    if virt and virt not in ("none", "unknown", ""):
        return True
    joined = " ".join(value or "" for value in dmi.values()).lower()
    return any(marker in joined for marker in VIRTUAL_MARKERS)


def load_fixture(path: pathlib.Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        fail(f"fixture cannot be read: {exc}")
    if not isinstance(data, dict):
        fail("fixture root must be an object")
    return data


def digest_payload(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def collect(args: argparse.Namespace) -> dict[str, Any]:
    fixture = load_fixture(pathlib.Path(args.fixture)) if args.fixture else None

    if fixture is not None:
        lsblk = fixture.get("lsblk")
        findmnt = fixture.get("findmnt")
        if not isinstance(lsblk, dict) or not isinstance(findmnt, dict):
            fail("fixture requires lsblk and findmnt objects")
        boot_mode = str(fixture.get("bootMode") or "unknown")
        secure_boot = str(fixture.get("secureBootState") or "unknown")
        dmi_raw = fixture.get("dmi") or {}
        if not isinstance(dmi_raw, dict):
            fail("fixture dmi must be an object")
        dmi = {key: str(dmi_raw.get(key) or "") or None for key in DMI_PATHS}
        virt = str(fixture.get("virtualization") or "unknown")
        kernel = str(fixture.get("kernel") or "fixture-kernel")
        arch = str(fixture.get("architecture") or "x86_64")
        persistence = fixture.get("persistenceMarker")
        if persistence is not None and not isinstance(persistence, str):
            fail("fixture persistenceMarker must be a string or null")
    else:
        lsblk = run_json([
            "/usr/bin/lsblk", "--json", "--paths", "--bytes",
            "-o", "NAME,KNAME,PKNAME,TYPE,TRAN,RM,RO,SIZE,FSTYPE,LABEL,MOUNTPOINTS,MODEL,SERIAL",
        ])
        findmnt = run_json(["/usr/bin/findmnt", "--json", "--canonicalize", "-n", "-o", "SOURCE,FSTYPE,TARGET", "/"])
        boot_mode = "uefi" if pathlib.Path("/sys/firmware/efi").is_dir() else "legacy-or-unknown"
        secure_boot = secure_boot_state()
        dmi = {key: read_text(path) for key, path in DMI_PATHS.items()}
        try:
            virt_result = subprocess.run(
                ["/usr/bin/systemd-detect-virt"],
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=5,
            )
            virt = virt_result.stdout.strip() if virt_result.returncode == 0 else "none"
        except (FileNotFoundError, subprocess.TimeoutExpired):
            virt = "unknown"
        kernel = platform.release()
        arch = platform.machine()
        persistence = read_text(PERSISTENCE_MARKER, limit=512)

    devices = normalize_lsblk(lsblk)
    root_source, root_fstype = first_mount_source(findmnt)
    chain = root_device_chain(root_source, devices)
    root_leaf = chain[0] if chain else None
    root_disk = chain[-1] if chain else None
    usb_transport = bool(root_disk and str(root_disk.get("tran") or "").lower() == "usb")
    live_label = bool(root_leaf and str(root_leaf.get("label") or "") == LIVE_ROOT_LABEL)
    virtual = looks_virtual(dmi, virt)

    physical_candidate = bool(
        args.phase == "live"
        and boot_mode == "uefi"
        and usb_transport
        and live_label
        and not virtual
    )
    installed_candidate = bool(
        args.phase == "installed"
        and boot_mode == "uefi"
        and root_disk
        and str(root_disk.get("tran") or "").lower() != "usb"
        and not virtual
        and persistence
    )

    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "phase": args.phase,
        "capturedAtUtc": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "collector": {
            "readOnly": True,
            "requiresRoot": False,
            "destructiveActions": False,
            "privacyMode": "serial-redacted",
        },
        "system": {
            "architecture": arch,
            "kernel": kernel,
            "bootMode": boot_mode,
            "secureBootStateObserved": secure_boot,
            "secureBootSupportClaim": False,
            "virtualization": virt,
            "virtualizationHeuristic": virtual,
            "dmi": dmi,
        },
        "root": {
            "source": root_source,
            "filesystem": root_fstype,
            "leafLabel": str(root_leaf.get("label") or "") if root_leaf else None,
            "parentTransport": str(root_disk.get("tran") or "") if root_disk else None,
            "sourceChain": [safe_device_summary(item) for item in chain],
        },
        "blockDevices": [safe_device_summary(item) for item in devices],
        "liveUsbEvidence": {
            "expectedRootLabel": LIVE_ROOT_LABEL,
            "rootLabelMatches": live_label,
            "rootParentTransportIsUsb": usb_transport,
            "physicalCandidate": physical_candidate,
        },
        "installedBootEvidence": {
            "rootParentTransportIsUsb": bool(root_disk and str(root_disk.get("tran") or "").lower() == "usb"),
            "persistenceMarkerPresent": bool(persistence),
            "persistenceMarkerSha256": hashlib.sha256(persistence.encode("utf-8")).hexdigest() if persistence else None,
            "installedCandidate": installed_candidate,
        },
        "claims": {
            "physicalHardwareQualificationClaim": False,
            "secureBootSupportClaim": False,
            "legacyBiosSupportClaim": False,
            "allPcCompatibilityClaim": False,
        },
        "reviewRequired": [
            "boot the final SWIR image from a physically written USB device",
            "verify the Live session does not write internal disks without explicit installer action",
            "exercise wrong-target refusal and cancel-without-mutation on dedicated test hardware",
            "install to a separate empty test disk only after explicit human confirmation",
            "power off, detach source USB, boot the installed disk and verify persistence",
        ],
    }
    payload["evidenceDigestSha256"] = digest_payload(payload)
    return payload


def write_output(path_text: str, data: bytes) -> None:
    path = pathlib.Path(path_text)
    if path.is_symlink():
        fail("refusing symlink output path")
    parent = path.parent if path.parent != pathlib.Path("") else pathlib.Path(".")
    if not parent.exists() or not parent.is_dir():
        fail("output parent directory does not exist")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(path, flags, 0o600)
    except FileExistsError:
        fail("refusing to overwrite existing evidence file")
    except OSError as exc:
        fail(f"cannot create evidence file: {exc}")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=("live", "installed"), required=True)
    parser.add_argument("--output", help="create a new mode-0600 JSON evidence file; existing files are never overwritten")
    parser.add_argument("--fixture", help=argparse.SUPPRESS)
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    payload = collect(args)
    rendered = (json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")
    if args.output:
        write_output(args.output, rendered)
    else:
        sys.stdout.buffer.write(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
