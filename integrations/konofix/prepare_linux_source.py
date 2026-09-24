#!/usr/bin/env python3
"""Apply the minimal SWIR OS Linux desktop integration overlay to pinned Konofix 0.5.1.

The upstream project remains authoritative. This helper refuses dirty or wrong-revision
source trees and changes only platform dependency/build gating needed to compile the
same Tauri client natively on Linux. It does not modify protocol, UI, identity or data.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys

SOURCE_COMMIT = "31298cc732c97ff90230c3743cd1c3be17f40b6c"
EXPECTED_FILES = {
    "src-tauri/Cargo.toml",
    "src-tauri/build.rs",
    "src-tauri/src/main.rs",
}


class IntegrationError(RuntimeError):
    pass


def git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    if result.returncode != 0:
        raise IntegrationError(f"git {' '.join(args)} failed")
    return result.stdout.strip()


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise IntegrationError(f"{label}: expected exactly one source fragment, found {count}")
    return text.replace(old, new, 1)


def apply(root: Path) -> list[str]:
    root = root.resolve()
    if not (root / ".git").exists():
        raise IntegrationError("Konofix source root is not a Git checkout")
    if git(root, "rev-parse", "HEAD") != SOURCE_COMMIT:
        raise IntegrationError("Konofix source checkout is not the reviewed 0.5.1 source commit")
    if git(root, "status", "--porcelain", "--untracked-files=all"):
        raise IntegrationError("Konofix source checkout must be clean before applying the overlay")

    cargo_path = root / "src-tauri" / "Cargo.toml"
    cargo = cargo_path.read_text(encoding="utf-8")
    cargo = replace_once(
        cargo,
        "[target.'cfg(windows)'.build-dependencies]\ntauri-build = { version = \"2\", features = [] }",
        "[target.'cfg(any(windows, target_os = \"linux\"))'.build-dependencies]\ntauri-build = { version = \"2\", features = [] }",
        "Cargo build dependency gate",
    )
    cargo = replace_once(
        cargo,
        "[target.'cfg(windows)'.dependencies]\ntauri = { version = \"2\", features = [] }\nrfd = \"0.17.2\"",
        "[target.'cfg(any(windows, target_os = \"linux\"))'.dependencies]\ntauri = { version = \"2\", features = [] }\nrfd = \"0.17.2\"",
        "Cargo desktop dependency gate",
    )
    cargo_path.write_text(cargo, encoding="utf-8", newline="\n")

    build_path = root / "src-tauri" / "build.rs"
    build = build_path.read_text(encoding="utf-8")
    build = replace_once(
        build,
        '#[cfg(windows)]\nfn build_desktop_app() {\n    tauri_build::build();\n}\n\n#[cfg(not(windows))]\nfn build_desktop_app() {\n    // The desktop application is currently a Windows target. Keeping the Tauri build hook\n    // out of non-Windows builds lets the headless Konofix Node compile on a minimal Linux VPS\n    // without pulling GUI/WebKit development dependencies into the server build.\n}',
        '#[cfg(any(windows, target_os = "linux"))]\nfn build_desktop_app() {\n    tauri_build::build();\n}\n\n#[cfg(not(any(windows, target_os = "linux")))]\nfn build_desktop_app() {\n    // Desktop integration is currently qualified by upstream on Windows and by SWIR OS on Linux.\n}',
        "Tauri build hook gate",
    )
    build_path.write_text(build, encoding="utf-8", newline="\n")

    main_path = root / "src-tauri" / "src" / "main.rs"
    main = main_path.read_text(encoding="utf-8")
    main = replace_once(
        main,
        '#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]',
        '#![cfg_attr(all(windows, not(debug_assertions)), windows_subsystem = "windows")]',
        "Windows subsystem attribute gate",
    )
    main_path.write_text(main, encoding="utf-8", newline="\n")

    changed = {line.strip() for line in git(root, "diff", "--name-only").splitlines() if line.strip()}
    if changed != EXPECTED_FILES:
        raise IntegrationError(f"unexpected overlay file set: {sorted(changed)}")
    return sorted(changed)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    args = parser.parse_args(argv)
    try:
        changed = apply(args.source)
    except (IntegrationError, OSError) as error:
        print(f"Konofix Linux integration overlay failed: {error}", file=sys.stderr)
        return 1
    print("\n".join(changed))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
