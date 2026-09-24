#!/usr/bin/env python3
"""Read-only verifier for a staged Konofix System root."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import sys

SOURCE_COMMIT = "31298cc732c97ff90230c3743cd1c3be17f40b6c"
APP = Path("opt/swir/apps/konofix/konofix-chat")
ICON = Path("usr/share/icons/hicolor/256x256/apps/konofix-chat.png")
DESKTOP = Path("usr/share/applications/konofix-chat.desktop")
PROVENANCE = Path("usr/share/swir/provenance/konofix-chat.json")
PNG = b"\x89PNG\r\n\x1a\n"

class VerifyError(RuntimeError):
    pass

def read_regular(path: Path, limit: int) -> bytes:
    info = path.lstat()
    if path.is_symlink() or not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= limit:
        raise VerifyError(f"invalid staged file: {path}")
    data = path.read_bytes()
    if len(data) != info.st_size:
        raise VerifyError(f"staged file changed while reading: {path}")
    return data

def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def verify(root: Path) -> dict:
    if root.is_symlink() or not root.is_dir():
        raise VerifyError("root must be a real directory")
    root = root.resolve(strict=True)
    evidence = json.loads(read_regular(root / PROVENANCE, 64 * 1024).decode("utf-8"))
    if evidence.get("schema") != "swir.konofix-system-native/1.0":
        raise VerifyError("unexpected provenance schema")
    if evidence.get("sourceCommit") != SOURCE_COMMIT:
        raise VerifyError("unexpected Konofix source commit")
    if evidence.get("executedDuringStage") is not False or evidence.get("legacyChatDataImported") is not False:
        raise VerifyError("unsafe staging side effect recorded")

    checks = (
        ("binary", APP, 64 * 1024 * 1024, 0o755),
        ("icon", ICON, 4 * 1024 * 1024, 0o644),
        ("desktop", DESKTOP, 64 * 1024, 0o644),
    )
    for key, relative, limit, mode in checks:
        path = root / relative
        data = read_regular(path, limit)
        if path.lstat().st_mode & 0o777 != mode:
            raise VerifyError(f"mode mismatch for {relative}")
        record = evidence.get(key) or {}
        if record.get("path") != "/" + relative.as_posix() or record.get("sha256") != digest(data):
            raise VerifyError(f"provenance mismatch for {relative}")
        if key == "binary":
            if not data.startswith(b"\x7fELF") or record.get("size") != len(data):
                raise VerifyError("binary identity mismatch")
        elif key == "icon" and not data.startswith(PNG):
            raise VerifyError("icon is not PNG")
        elif key == "desktop":
            text = data.decode("utf-8").splitlines()
            for required in (
                "Name=Konofix Chat",
                "Exec=/opt/swir/apps/konofix/konofix-chat",
                "TryExec=/opt/swir/apps/konofix/konofix-chat",
                "Icon=konofix-chat",
                "Terminal=false",
            ):
                if required not in text:
                    raise VerifyError(f"desktop contract missing {required}")
    return evidence

def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        print(json.dumps(verify(args.root), sort_keys=True))
        return 0
    except (OSError, UnicodeError, ValueError, VerifyError, json.JSONDecodeError) as exc:
        print(f"Konofix System verification failed: {exc}", file=sys.stderr)
        return 1

if __name__ == "__main__":
    raise SystemExit(main())
