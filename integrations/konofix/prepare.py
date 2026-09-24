#!/usr/bin/env python3
"""Prepare the pinned Konofix Windows installer. Never install or execute it.

Only the reviewed upstream.json asset is exposed by the CLI. This is the first
OS-side integration step, not a replacement chat client or a Linux GUI port.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import stat
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

CHUNK = 128 * 1024
MAX_SIZE = 200 * 1024 * 1024


class PreparationError(Exception):
    """A download or integrity boundary failed; no installer is executed."""


def trusted_url(url: str, initial_url: str) -> bool:
    """No credentials, plaintext, nonstandard ports or arbitrary CDN hosts."""
    try:
        parsed = urllib.parse.urlsplit(url)
        if any(ord(char) < 33 or ord(char) == 127 for char in url):
            return False
        if parsed.scheme != "https" or parsed.username or parsed.password or parsed.fragment:
            return False
        if parsed.port not in (None, 443):
            return False
        return url == initial_url or parsed.hostname == "release-assets.githubusercontent.com"
    except (ValueError, TypeError):
        return False


class ReleaseRedirects(urllib.request.HTTPRedirectHandler):
    def __init__(self, initial_url: str) -> None:
        self.initial_url = initial_url
        self.count = 0

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        self.count += 1
        if self.count > 3 or not trusted_url(newurl, self.initial_url):
            raise PreparationError("Rejected release redirect.")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


@dataclass(frozen=True)
class Asset:
    name: str
    url: str
    size: int
    sha256: str

    def __post_init__(self) -> None:
        match = re.fullmatch(r"Konofix-Chat-([0-9]+\.[0-9]+\.[0-9]+)-x64-Setup\.exe", self.name)
        if not match or self.url != f"https://github.com/Swir/Konofix/releases/download/v{match[1]}/{self.name}":
            raise PreparationError("Only the official version-pinned Windows asset is allowed.")
        if type(self.size) is not int or not 0 < self.size <= MAX_SIZE:
            raise PreparationError("Invalid asset size.")
        if not re.fullmatch(r"[0-9a-f]{64}", self.sha256):
            raise PreparationError("Invalid asset SHA-256.")


def load_asset(path: Path = Path(__file__).with_name("upstream.json")) -> Asset:
    if path.stat().st_size > 16384:
        raise PreparationError("Upstream pin exceeds its size bound.")
    pin = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(pin, dict):
        raise PreparationError("Upstream pin must be an object.")
    version = pin.get("version", "")
    if not isinstance(version, str) or not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version):
        raise PreparationError("Only an explicit stable version is supported.")
    name = f"Konofix-Chat-{version}-x64-Setup.exe"
    url = f"https://github.com/Swir/Konofix/releases/download/v{version}/{name}"
    expected = {"schema": "swir.konofix-upstream/1.0", "repository": "Swir/Konofix",
                "tag": f"v{version}", "platform": "windows-x86_64", "fileName": name,
                "url": url, "linuxGuiQualified": False, "automaticExecution": False}
    if any(pin.get(key) != value for key, value in expected.items()) or any(
            pin.get(key) is not False for key in ("linuxGuiQualified", "automaticExecution")):
        raise PreparationError("Unsupported upstream identity, platform or execution policy.")
    if type(pin.get("size")) is not int or not 0 < pin["size"] <= MAX_SIZE:
        raise PreparationError("Invalid pinned asset size.")
    if not isinstance(pin.get("sha256"), str) or not re.fullmatch(r"[0-9a-f]{64}", pin["sha256"]):
        raise PreparationError("Invalid SHA-256 pin.")
    if not isinstance(pin.get("sourceCommit"), str) or not re.fullmatch(r"[0-9a-f]{40}", pin["sourceCommit"]):
        raise PreparationError("A full source commit is required.")
    if any(type(pin.get(key)) is not int or pin[key] <= 0 for key in ("releaseId", "assetId")):
        raise PreparationError("Release and asset identifiers are required.")
    return Asset(name, url, pin["size"], pin["sha256"])


def verify(path: Path, asset: Asset) -> None:
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or before.st_size != asset.size:
        raise PreparationError("Installer is not a regular file of the pinned size.")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    with os.fdopen(os.open(path, flags), "rb") as source:
        opened = os.fstat(source.fileno())
        if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
            raise PreparationError("Installer changed while being opened.")
        digest = hashlib.sha256()
        size = 0
        while chunk := source.read(CHUNK):
            size += len(chunk)
            if size > asset.size:
                raise PreparationError("Installer exceeds its pinned size.")
            digest.update(chunk)
        after = os.fstat(source.fileno())
    if size != asset.size or (opened.st_size, opened.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise PreparationError("Installer size or contents changed during verification.")
    if not hmac.compare_digest(digest.hexdigest(), asset.sha256):
        raise PreparationError("Installer SHA-256 mismatch.")


def prepare(asset: Asset, output: Path, *, opener=None) -> Path:
    """Stage only verified bytes with atomic, no-overwrite publication."""
    if Path(asset.name).name != asset.name or "/" in asset.name or "\\" in asset.name or ":" in asset.name:
        raise PreparationError("Invalid asset filename.")
    if type(asset.size) is not int or not 0 < asset.size <= MAX_SIZE:
        raise PreparationError("Invalid asset size.")
    output.mkdir(parents=True, exist_ok=True, mode=0o700)
    if output.is_symlink() or not output.is_dir():
        raise PreparationError("Output must be a directory, not a symbolic link.")
    target = output / asset.name
    if os.path.lexists(target):
        verify(target, asset)
        return target  # Verified reruns do not download or overwrite anything.

    if opener is None:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), ReleaseRedirects(asset.url))
    request = urllib.request.Request(asset.url, headers={
        "User-Agent": "SWIR-OS-Konofix-Preparation/1.0", "Accept-Encoding": "identity"})
    fd, temp_name = tempfile.mkstemp(prefix=".konofix-", suffix=".partial", dir=output)
    temporary = Path(temp_name)
    try:
        with os.fdopen(fd, "wb") as sink, opener.open(request, timeout=30) as response:
            if response.status != 200 or not trusted_url(response.geturl(), asset.url):
                raise PreparationError("Unexpected release response.")
            if response.headers.get("Content-Encoding", "identity").lower() not in ("", "identity"):
                raise PreparationError("Encoded release responses are not accepted.")
            length = response.headers.get("Content-Length")
            if length is not None and (not str(length).isdecimal() or int(length) != asset.size):
                raise PreparationError("Release Content-Length differs from its pin.")
            received = 0
            deadline = time.monotonic() + 120
            while chunk := response.read(min(CHUNK, asset.size - received + 1)):
                if time.monotonic() > deadline:
                    raise PreparationError("Release download exceeded its time budget.")
                received += len(chunk)
                if received > asset.size:
                    raise PreparationError("Release response exceeds its pinned size.")
                sink.write(chunk)
            sink.flush()
            os.fsync(sink.fileno())
        verify(temporary, asset)
        # Unlike replace/rename on POSIX, link fails if another process created
        # the target. A filesystem without hard links fails closed, not in-place.
        os.link(temporary, target)
        return target
    finally:
        temporary.unlink(missing_ok=True)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--output", type=Path, help="Directory for a verified download; never auto-runs")
    group.add_argument("--verify", type=Path, help="Check an existing installer without using the network")
    args = parser.parse_args(argv)
    try:
        asset = load_asset()
        if args.verify is not None:
            verify(args.verify, asset)
            path = args.verify
        else:
            path = prepare(asset, args.output)
        print(json.dumps({"status": "verified-download-only", "file": str(path),
                          "sha256": asset.sha256, "size": asset.size,
                          "installed": False, "executed": False, "linuxGuiQualified": False}))
        return 0
    except (PreparationError, OSError, ValueError, urllib.error.URLError) as error:
        # Do not leak temporary signed CDN query strings through HTTP exceptions.
        message = str(error) if isinstance(error, PreparationError) else type(error).__name__
        print(f"Konofix preparation failed: {message}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
