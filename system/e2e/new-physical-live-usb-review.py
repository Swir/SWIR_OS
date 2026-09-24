#!/usr/bin/env python3
"""Create a privacy-minimized physical Live USB operator-review bundle.

The operator supplies a JSON map of required observations only after manually
performing the dedicated-hardware procedure. Raw hardware-scope text is hashed
locally and never written to the output. Existing files/symlinks are refused.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import importlib.util
import json
import os
import pathlib
import re
import sys
from typing import Any, Final

HEX64: Final = re.compile(r"^[0-9a-f]{64}$")
HEX40: Final = re.compile(r"^[0-9a-f]{40}$")


def fail(message: str) -> "NoReturn":
    raise SystemExit(f"physical review creation failed: {message}")


def load_module(filename: str, name: str) -> Any:
    path = pathlib.Path(__file__).with_name(filename)
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        fail(f"cannot load {filename}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_observations(path_text: str, required: tuple[str, ...]) -> dict[str, bool]:
    path = pathlib.Path(path_text)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        fail(f"cannot read observations file: {exc}")
    if not isinstance(data, dict):
        fail("observations file must contain a JSON object")
    unknown = sorted(set(data) - set(required))
    missing = [name for name in required if data.get(name) is not True]
    if unknown:
        fail(f"unknown observation keys: {', '.join(unknown)}")
    if missing:
        fail(f"all required observations must be explicitly true: {', '.join(missing)}")
    return {name: True for name in required}


def write_exclusive(path_text: str, payload: bytes) -> None:
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
        fail("refusing to overwrite existing review file")
    except OSError as exc:
        fail(f"cannot create review file: {exc}")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", required=True)
    parser.add_argument("--installed", required=True)
    parser.add_argument("--observations", required=True)
    parser.add_argument("--image-sha256", required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--image-bytes", required=True, type=int)
    parser.add_argument("--hardware-scope", required=True, help="local hardware-scope label; only its SHA-256 is stored")
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)

    if not HEX64.fullmatch(args.image_sha256):
        fail("--image-sha256 must be lowercase 64-character SHA-256 hex")
    if not HEX40.fullmatch(args.source_commit):
        fail("--source-commit must be a full lowercase 40-character Git SHA")
    if args.image_bytes <= 0:
        fail("--image-bytes must be positive")
    scope = args.hardware_scope.strip()
    if not scope or len(scope) > 512:
        fail("--hardware-scope must contain 1..512 characters")

    sequence = load_module("verify-physical-live-usb-sequence.py", "swir_physical_sequence")
    review_module = load_module("verify-physical-live-usb-review.py", "swir_physical_review")
    live = sequence.load_regular_json(args.live)
    installed = sequence.load_regular_json(args.installed)
    sequence.verify_pair(live, installed)
    observations = load_observations(args.observations, tuple(review_module.REQUIRED_OBSERVATIONS))

    payload: dict[str, Any] = {
        "schema": review_module.REVIEW_SCHEMA,
        "reviewedAtUtc": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "sourceImage": {
            "sha256": args.image_sha256,
            "sourceCommit": args.source_commit,
            "bytes": args.image_bytes,
        },
        "hardwareScope": {
            "privacySafeIdSha256": hashlib.sha256(scope.encode("utf-8")).hexdigest(),
            "serialsStored": False,
        },
        "evidenceBinding": {
            "liveEvidenceDigestSha256": live["evidenceDigestSha256"],
            "installedEvidenceDigestSha256": installed["evidenceDigestSha256"],
        },
        "observations": observations,
        "claims": {
            "secureBootSupportClaim": False,
            "legacyBiosSupportClaim": False,
            "allPcCompatibilityClaim": False,
        },
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    payload["reviewDigestSha256"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    review_module.verify_review(payload, live, installed)
    rendered = (json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")
    write_exclusive(args.output, rendered)
    print(json.dumps({
        "schema": "swir.physical-live-usb-review-creation/1.0",
        "created": True,
        "output": str(pathlib.Path(args.output)),
        "rawHardwareScopeStored": False,
        "physicalHardwareRoadmapCompletionClaimed": False,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
