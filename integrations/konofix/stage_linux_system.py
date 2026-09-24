#!/usr/bin/env python3
"""Stage the exact reviewed native Konofix build into a disposable SWIR System root."""
from __future__ import annotations
import argparse, hashlib, json, os, stat, subprocess, sys
from pathlib import Path

SOURCE_COMMIT = "31298cc732c97ff90230c3743cd1c3be17f40b6c"
EXPECTED_STATUS = {
    " M src-tauri/Cargo.toml",
    " M src-tauri/build.rs",
    " M src-tauri/src/main.rs",
    "?? src-tauri/icons/icon.png",
}
# Tauri 2 emits these deterministic, untracked JSON schemas during a release
# build. They are tooling output rather than reviewed source-overlay changes.
# Accept exactly this fixed set after the binary has been built; any additional
# generated or arbitrary untracked path still fails closed.
EXPECTED_BUILD_GENERATED_STATUS = {
    "?? src-tauri/gen/schemas/acl-manifests.json",
    "?? src-tauri/gen/schemas/capabilities.json",
    "?? src-tauri/gen/schemas/desktop-schema.json",
    "?? src-tauri/gen/schemas/linux-schema.json",
}
BINARY_REL = Path("src-tauri/target/release/konofix-chat")
ICON_REL = Path("src-tauri/icons/icon.png")
APP_DEST = Path("opt/swir/apps/konofix/konofix-chat")
ICON_DEST = Path("usr/share/icons/hicolor/256x256/apps/konofix-chat.png")
DESKTOP_DEST = Path("usr/share/applications/konofix-chat.desktop")
PROVENANCE_DEST = Path("usr/share/swir/provenance/konofix-chat.json")
PNG = b"\x89PNG\r\n\x1a\n"

class StageError(RuntimeError):
    pass

def git(root: Path, *args: str) -> str:
    p = subprocess.run(["git","-C",str(root),*args], stdout=subprocess.PIPE,
                       stderr=subprocess.PIPE, text=True, encoding="utf-8")
    if p.returncode:
        raise StageError("git source verification failed")
    return p.stdout.rstrip("\n")

def read_regular(path: Path, limit: int) -> bytes:
    info = path.lstat()
    if path.is_symlink() or not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= limit:
        raise StageError(f"invalid regular input: {path}")
    data = path.read_bytes()
    if len(data) != info.st_size:
        raise StageError(f"input changed while reading: {path}")
    return data

def validate_source(source: Path) -> tuple[Path, Path]:
    source = source.resolve(strict=True)
    if git(source, "rev-parse", "HEAD").strip() != SOURCE_COMMIT:
        raise StageError("source is not the pinned Konofix 0.5.1 commit")
    status = set(filter(None, git(source, "status", "--porcelain", "--untracked-files=all").splitlines()))
    allowed_states = (EXPECTED_STATUS, EXPECTED_STATUS | EXPECTED_BUILD_GENERATED_STATUS)
    if status not in allowed_states:
        raise StageError(f"unexpected source overlay state: {sorted(status)}")
    return source / BINARY_REL, source / ICON_REL

def validate_desktop(text: str) -> None:
    required = [
        "[Desktop Entry]", "Type=Application", "Name=Konofix Chat",
        "Exec=/opt/swir/apps/konofix/konofix-chat",
        "TryExec=/opt/swir/apps/konofix/konofix-chat",
        "Icon=konofix-chat", "Terminal=false",
    ]
    if any(item not in text.splitlines() for item in required):
        raise StageError("desktop entry drifted from the fixed System launch contract")

def write_new(path: Path, data: bytes, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if os.path.lexists(path):
        raise StageError(f"refusing to overwrite staged path: {path}")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    fd = os.open(path, flags, mode)
    try:
        with os.fdopen(fd, "wb", closefd=False) as stream:
            stream.write(data); stream.flush(); os.fsync(stream.fileno())
    finally:
        os.close(fd)
    os.chmod(path, mode)

def stage(source: Path, root: Path, desktop: Path) -> dict:
    binary, icon = validate_source(source)
    binary_data = read_regular(binary, 64 * 1024 * 1024)
    icon_data = read_regular(icon, 4 * 1024 * 1024)
    desktop_data = read_regular(desktop, 64 * 1024)
    if not binary_data.startswith(b"\x7fELF"):
        raise StageError("native candidate is not ELF")
    if not icon_data.startswith(PNG):
        raise StageError("native icon is not PNG")
    validate_desktop(desktop_data.decode("utf-8"))
    root.mkdir(parents=True, exist_ok=True)
    if root.is_symlink() or not root.is_dir():
        raise StageError("staging root must be a real directory")
    root = root.resolve(strict=True)
    write_new(root / APP_DEST, binary_data, 0o755)
    write_new(root / ICON_DEST, icon_data, 0o644)
    write_new(root / DESKTOP_DEST, desktop_data, 0o644)
    evidence = {
        "schema": "swir.konofix-system-native/1.0",
        "version": "0.5.1",
        "sourceCommit": SOURCE_COMMIT,
        "binary": {"path": "/" + APP_DEST.as_posix(), "sha256": hashlib.sha256(binary_data).hexdigest(), "size": len(binary_data)},
        "icon": {"path": "/" + ICON_DEST.as_posix(), "sha256": hashlib.sha256(icon_data).hexdigest()},
        "desktop": {"path": "/" + DESKTOP_DEST.as_posix(), "sha256": hashlib.sha256(desktop_data).hexdigest()},
        "executedDuringStage": False,
        "legacyChatDataImported": False,
    }
    write_new(root / PROVENANCE_DEST, (json.dumps(evidence, sort_keys=True, indent=2)+"\n").encode(), 0o644)
    return evidence

def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--source", type=Path, required=True)
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--desktop", type=Path, required=True)
    a = p.parse_args(argv)
    try:
        print(json.dumps(stage(a.source, a.root, a.desktop), sort_keys=True))
        return 0
    except (OSError, UnicodeError, ValueError, StageError) as exc:
        print(f"Konofix System staging failed: {exc}", file=sys.stderr)
        return 1

if __name__ == "__main__":
    raise SystemExit(main())
