#!/usr/bin/env python3
"""Apply the minimal SWIR OS Linux desktop overlay to pinned Konofix 0.5.1."""
from __future__ import annotations

import argparse
import binascii
from pathlib import Path
import struct
import subprocess
import sys
import zlib

SOURCE_COMMIT = "31298cc732c97ff90230c3743cd1c3be17f40b6c"
ICON_BLOB_SHA = "b5dfa830f08ae2c558403d4e6e70bba9ef140329"
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
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


def png_chunk(kind: bytes, data: bytes) -> bytes:
    crc = binascii.crc32(kind)
    crc = binascii.crc32(data, crc) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", crc)


def encode_rgba_png(width: int, height: int, rows: list[bytes]) -> bytes:
    if width <= 0 or height <= 0 or len(rows) != height:
        raise IntegrationError("invalid icon dimensions")
    if any(len(row) != width * 4 for row in rows):
        raise IntegrationError("invalid RGBA row width")
    scanlines = b"".join(b"\x00" + row for row in rows)
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return (
        PNG_SIGNATURE
        + png_chunk(b"IHDR", ihdr)
        + png_chunk(b"IDAT", zlib.compress(scanlines, 9))
        + png_chunk(b"IEND", b"")
    )


def ico_entry_to_png(payload: bytes, width_hint: int, height_hint: int) -> bytes:
    if payload.startswith(PNG_SIGNATURE):
        return payload
    if len(payload) < 40:
        raise IntegrationError("unsupported short ICO bitmap payload")
    header_size, width, doubled_height, planes, bit_count, compression = struct.unpack_from("<IiiHHI", payload, 0)
    if header_size < 40 or header_size > len(payload):
        raise IntegrationError("invalid ICO bitmap header")
    if width <= 0 or doubled_height == 0 or planes != 1 or bit_count not in (24, 32) or compression != 0:
        raise IntegrationError("unsupported ICO bitmap format")
    height = abs(doubled_height) // 2
    if height <= 0 or (width_hint and width_hint != width) or (height_hint and height_hint != height):
        raise IntegrationError("ICO directory and bitmap dimensions differ")
    row_stride = ((width * bit_count + 31) // 32) * 4
    pixels_offset = header_size
    pixels_end = pixels_offset + row_stride * height
    if pixels_end > len(payload):
        raise IntegrationError("truncated ICO pixel payload")
    mask_stride = ((width + 31) // 32) * 4
    mask_offset = pixels_end
    has_mask = mask_offset + mask_stride * height <= len(payload)
    rows: list[bytes] = []
    any_alpha = False
    for output_y in range(height):
        source_y = output_y if doubled_height < 0 else height - 1 - output_y
        base = pixels_offset + source_y * row_stride
        rgba = bytearray()
        for x in range(width):
            if bit_count == 32:
                blue, green, red, alpha = payload[base + x * 4: base + x * 4 + 4]
                any_alpha = any_alpha or alpha != 0
            else:
                blue, green, red = payload[base + x * 3: base + x * 3 + 3]
                alpha = 255
            rgba.extend((red, green, blue, alpha))
        rows.append(bytes(rgba))
    if bit_count == 32 and not any_alpha:
        fixed: list[bytes] = []
        for row in rows:
            mutable = bytearray(row)
            for x in range(width):
                mutable[x * 4 + 3] = 255
            fixed.append(bytes(mutable))
        rows = fixed
    if has_mask:
        adjusted: list[bytes] = []
        for output_y, row in enumerate(rows):
            source_y = output_y if doubled_height < 0 else height - 1 - output_y
            mask_base = mask_offset + source_y * mask_stride
            mutable = bytearray(row)
            for x in range(width):
                if payload[mask_base + (x // 8)] & (0x80 >> (x % 8)):
                    mutable[x * 4 + 3] = 0
            adjusted.append(bytes(mutable))
        rows = adjusted
    return encode_rgba_png(width, height, rows)


def materialize_linux_icon(root: Path) -> Path:
    ico = root / "src-tauri" / "icons" / "icon.ico"
    png = root / "src-tauri" / "icons" / "icon.png"
    if png.exists():
        raise IntegrationError("unexpected pre-existing Linux icon")
    if git(root, "hash-object", "src-tauri/icons/icon.ico") != ICON_BLOB_SHA:
        raise IntegrationError("Konofix icon blob differs from reviewed 0.5.1 branding")
    raw = ico.read_bytes()
    if len(raw) < 6:
        raise IntegrationError("invalid ICO header")
    reserved, image_type, count = struct.unpack_from("<HHH", raw, 0)
    if reserved != 0 or image_type != 1 or count <= 0 or len(raw) < 6 + 16 * count:
        raise IntegrationError("invalid ICO directory")
    candidates = []
    for index in range(count):
        offset = 6 + index * 16
        width_byte, height_byte, _colors, _reserved, _planes, bpp, size, image_offset = struct.unpack_from("<BBBBHHII", raw, offset)
        width = width_byte or 256
        height = height_byte or 256
        if size <= 0 or image_offset < 6 + 16 * count or image_offset + size > len(raw):
            raise IntegrationError("invalid ICO image bounds")
        candidates.append((width * height, bpp, width, height, raw[image_offset:image_offset + size]))
    failures = []
    for _area, _bpp, width, height, payload in sorted(candidates, reverse=True):
        try:
            png_bytes = ico_entry_to_png(payload, width, height)
            if not png_bytes.startswith(PNG_SIGNATURE):
                raise IntegrationError("generated icon is not PNG")
            png.write_bytes(png_bytes)
            return png
        except IntegrationError as error:
            failures.append(str(error))
    raise IntegrationError("no ICO image could be converted to PNG: " + "; ".join(failures))


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
        '#[cfg(any(windows, target_os = "linux"))]\nfn build_desktop_app() {\n    tauri_build::build();\n}\n\n#[cfg(not(any(windows, target_os = "linux")))]\nfn build_desktop_app() {\n    // Desktop integration remains disabled outside the reviewed desktop targets.\n}',
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

    materialize_linux_icon(root)

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
