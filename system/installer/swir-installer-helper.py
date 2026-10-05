#!/usr/bin/env python3
"""Privileged helper for the SWIR OS graphical Live installer.

The helper accepts exactly one JSON request on stdin, validates all user-facing
configuration before any disk mutation, delegates destructive partition/install
work to the existing guarded install engine, then configures the newly installed
root while it is mounted privately. It is intentionally not a general-purpose
root command runner.
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import stat
import subprocess
import sys
import tempfile
from typing import Any, NoReturn

ENGINE = pathlib.Path("/usr/local/sbin/swir-install-engine")
LIVE_MARKER = pathlib.Path("/var/lib/swir/live/live.json")
E2E_MARKER = pathlib.Path("/run/swir/installer-e2e-enabled")
MAX_PASSWORD_BYTES = 256
MAX_LIVE_MARKER_BYTES = 4096
LIVE_MARKER_EXPECTED = {
    "schema": "swir.live-media/0.1",
    "mode": "live",
    "installerAllowed": True,
    "readOnlyFirst": True,
}
USERNAME_RE = re.compile(r"^[a-z_][a-z0-9_-]{0,30}$")
LOCALE_RE = re.compile(r"^[A-Za-z]{2,3}(?:_[A-Za-z]{2})?(?:\.[A-Za-z0-9_-]+)?$")
KEYBOARD_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
TIMEZONE_RE = re.compile(r"^[A-Za-z0-9_+.-]+(?:/[A-Za-z0-9_+.-]+)+$")


class InstallerError(RuntimeError):
    pass


def fail(message: str, code: int = 2) -> NoReturn:
    print(json.dumps({"schema": "swir.graphical-installer-result/0.1", "status": "error", "message": message}), file=sys.stdout)
    # The disposable full-path VM gate deliberately captures helper stdout in
    # the GTK process. Mirror only the already-sanitized failure message to the
    # VM serial console when the root-owned E2E marker exists so CI can diagnose
    # failures without weakening normal Live-media behavior or logging secrets.
    try:
        if E2E_MARKER.is_file() and not E2E_MARKER.is_symlink():
            st = E2E_MARKER.stat()
            if st.st_uid == 0 and not (stat.S_IMODE(st.st_mode) & 0o022):
                with open("/dev/ttyS0", "w", encoding="utf-8") as serial:
                    serial.write(f"SWIR_GRAPHICAL_INSTALLER_HELPER_FAIL {message}\n")
    except OSError:
        pass
    raise SystemExit(code)


def run(args: list[str], *, input_text: str | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, input=input_text, text=True, capture_output=True, check=check)


def validate_request(data: Any) -> dict[str, str]:
    if not isinstance(data, dict):
        raise InstallerError("request must be a JSON object")
    allowed = {"targetStablePath", "confirmationToken", "username", "password", "locale", "keyboard", "timezone"}
    extra = sorted(set(data) - allowed)
    if extra:
        raise InstallerError(f"unexpected request fields: {', '.join(extra)}")
    missing = sorted(k for k in allowed if not isinstance(data.get(k), str) or not data[k])
    if missing:
        raise InstallerError(f"missing required string fields: {', '.join(missing)}")

    target = data["targetStablePath"]
    token = data["confirmationToken"]
    username = data["username"]
    password = data["password"]
    locale = data["locale"]
    keyboard = data["keyboard"]
    timezone = data["timezone"]

    if not target.startswith("/dev/disk/by-id/") or "/../" in target or target.endswith("/.."):
        raise InstallerError("target must be a stable /dev/disk/by-id path")
    if not re.fullmatch(r"ERASE-SWIR-[0-9a-f]{12}", token):
        raise InstallerError("confirmation token format is invalid")
    if not USERNAME_RE.fullmatch(username) or username in {"root", "daemon", "bin", "sys", "sync", "games", "man", "lp", "mail", "news", "uucp", "proxy", "www-data", "backup", "list", "irc", "_apt", "nobody", "systemd-network", "systemd-timesync", "messagebus", "polkitd", "_greetd"}:
        raise InstallerError("username is invalid or reserved")
    password_bytes = password.encode("utf-8")
    if len(password_bytes) < 8 or len(password_bytes) > MAX_PASSWORD_BYTES or "\x00" in password or "\n" in password or "\r" in password:
        raise InstallerError("password must be 8-256 bytes and contain no line breaks")
    if not LOCALE_RE.fullmatch(locale):
        raise InstallerError("locale format is invalid")
    if not KEYBOARD_RE.fullmatch(keyboard):
        raise InstallerError("keyboard layout format is invalid")
    if not TIMEZONE_RE.fullmatch(timezone):
        raise InstallerError("timezone format is invalid")
    zoneinfo = pathlib.Path("/usr/share/zoneinfo") / timezone
    if not zoneinfo.is_file():
        raise InstallerError("timezone is not installed on this Live system")

    return {k: str(data[k]) for k in allowed}


def load_trusted_live_marker(path: pathlib.Path = LIVE_MARKER, *, expected_uid: int = 0) -> dict[str, Any]:
    try:
        parent = path.parent.lstat()
        before = path.lstat()
    except OSError as exc:
        raise InstallerError("trusted Live marker is unavailable") from exc
    if stat.S_ISLNK(parent.st_mode) or not stat.S_ISDIR(parent.st_mode):
        raise InstallerError("trusted Live marker directory must be a real directory")
    if parent.st_uid != expected_uid or stat.S_IMODE(parent.st_mode) & 0o022:
        raise InstallerError("trusted Live marker directory ownership/mode is unsafe")
    if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
        raise InstallerError("trusted Live marker must be a regular non-symlink file")
    if before.st_uid != expected_uid or stat.S_IMODE(before.st_mode) & 0o022:
        raise InstallerError("trusted Live marker ownership/mode is unsafe")
    if before.st_size <= 0 or before.st_size > MAX_LIVE_MARKER_BYTES:
        raise InstallerError("trusted Live marker size is invalid")

    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise InstallerError("trusted Live marker cannot be opened safely") from exc

    def signature(st: os.stat_result) -> tuple[int, int, int, int, int]:
        return (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns)

    try:
        opened = os.fstat(fd)
        if not stat.S_ISREG(opened.st_mode):
            raise InstallerError("trusted Live marker must remain a regular file")
        if opened.st_uid != expected_uid or stat.S_IMODE(opened.st_mode) & 0o022:
            raise InstallerError("trusted Live marker ownership/mode changed")
        if opened.st_size <= 0 or opened.st_size > MAX_LIVE_MARKER_BYTES:
            raise InstallerError("trusted Live marker size is invalid")
        if signature(opened) != signature(before):
            raise InstallerError("trusted Live marker changed before read")

        remaining = opened.st_size
        chunks: list[bytes] = []
        while remaining:
            chunk = os.read(fd, min(4096, remaining))
            if not chunk:
                raise InstallerError("trusted Live marker changed during read")
            chunks.append(chunk)
            remaining -= len(chunk)
        if os.read(fd, 1):
            raise InstallerError("trusted Live marker grew during read")
        after = os.fstat(fd)
        if signature(after) != signature(opened):
            raise InstallerError("trusted Live marker changed during read")
    finally:
        os.close(fd)

    try:
        payload = json.loads(b"".join(chunks).decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise InstallerError("trusted Live marker is not valid UTF-8 JSON") from exc
    if payload != LIVE_MARKER_EXPECTED:
        raise InstallerError("trusted Live marker authorization payload is invalid")
    return payload


def ensure_live_environment() -> None:
    if os.geteuid() != 0:
        raise InstallerError("helper requires root privileges")
    if not ENGINE.is_file() or ENGINE.is_symlink() or not os.access(ENGINE, os.X_OK):
        raise InstallerError("trusted install engine is unavailable")
    st = ENGINE.stat()
    if st.st_uid != 0 or stat.S_IMODE(st.st_mode) & 0o022:
        raise InstallerError("install engine ownership/mode is unsafe")
    load_trusted_live_marker()


def partition_for_label(disk: str, label: str) -> str:
    proc = run(["lsblk", "-J", "-p", "-o", "PATH,LABEL,TYPE", disk])
    tree = json.loads(proc.stdout)
    stack = list(tree.get("blockdevices") or [])
    while stack:
        node = stack.pop()
        if node.get("type") == "part" and node.get("label") == label and isinstance(node.get("path"), str):
            return node["path"]
        stack.extend(node.get("children") or [])
    raise InstallerError(f"installed partition with label {label} was not found")


def enable_locale(root_mount: pathlib.Path, locale: str) -> None:
    locale_gen = root_mount / "etc/locale.gen"
    if not locale_gen.is_file():
        raise InstallerError("installed system does not contain /etc/locale.gen")
    lines = locale_gen.read_text(encoding="utf-8").splitlines()
    wanted = f"{locale} UTF-8"
    normalized = []
    found = False
    for line in lines:
        stripped = line.strip()
        candidate = stripped.lstrip("#").strip()
        if candidate == wanted:
            normalized.append(wanted)
            found = True
        else:
            normalized.append(line)
    if not found:
        normalized.append(wanted)
    locale_gen.write_text("\n".join(normalized) + "\n", encoding="utf-8")
    run(["chroot", str(root_mount), "/usr/sbin/locale-gen", locale])


def configure_installed_root(root_mount: pathlib.Path, cfg: dict[str, str]) -> None:
    username = cfg["username"]
    password = cfg["password"]
    locale = cfg["locale"]
    keyboard = cfg["keyboard"]
    timezone = cfg["timezone"]

    user_exists = subprocess.run(
        ["chroot", str(root_mount), "/usr/bin/id", "-u", username],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    ).returncode == 0
    if user_exists:
        raise InstallerError("requested installed username already exists in source image")
    run(["chroot", str(root_mount), "/usr/sbin/useradd", "--create-home", "--shell", "/bin/bash", "--user-group", username])
    run(["chroot", str(root_mount), "/usr/sbin/chpasswd"], input_text=f"{username}:{password}\n")

    etc = root_mount / "etc"
    enable_locale(root_mount, locale)
    (etc / "locale.conf").write_text(f"LANG={locale}\n", encoding="utf-8")
    (etc / "default").mkdir(parents=True, exist_ok=True)
    (etc / "default" / "keyboard").write_text(
        f'XKBMODEL="pc105"\nXKBLAYOUT="{keyboard}"\nXKBVARIANT=""\nXKBOPTIONS=""\n', encoding="utf-8"
    )
    localtime = etc / "localtime"
    if localtime.exists() or localtime.is_symlink():
        localtime.unlink()
    localtime.symlink_to(f"/usr/share/zoneinfo/{timezone}")
    (etc / "timezone").write_text(timezone + "\n", encoding="utf-8")

    state_dir = root_mount / "var/lib/swir/install"
    state_dir.mkdir(parents=True, exist_ok=True)
    state = {
        "schema": "swir.system-install-user-config/0.1",
        "username": username,
        "locale": locale,
        "keyboard": keyboard,
        "timezone": timezone,
        "passwordStoredInEvidence": False,
    }
    state_path = state_dir / "user-config.json"
    state_path.write_text(json.dumps(state, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(state_path, 0o600)


def install(cfg: dict[str, str]) -> dict[str, Any]:
    target = cfg["targetStablePath"]
    preview_proc = run([str(ENGINE), "preview", "--target", target])
    preview = json.loads(preview_proc.stdout)
    if preview.get("confirmationToken") != cfg["confirmationToken"]:
        raise InstallerError("confirmation token is stale or does not match the current target identity")

    install_proc = run([str(ENGINE), "install", "--target", target, "--confirmation", cfg["confirmationToken"]])
    engine_result = json.loads(install_proc.stdout)
    if engine_result.get("status") != "installed":
        raise InstallerError("install engine did not return installed status")

    target_real = os.path.realpath(target)
    root_part = partition_for_label(target_real, "SWIR_ROOT")
    with tempfile.TemporaryDirectory(prefix="swir-configure-", dir="/run") as temp_dir:
        mount = pathlib.Path(temp_dir) / "root"
        mount.mkdir(mode=0o700)
        run(["mount", root_part, str(mount)])
        try:
            configure_installed_root(mount, cfg)
            run(["sync"])
        finally:
            subprocess.run(["umount", str(mount)], check=False)

    return {
        "schema": "swir.graphical-installer-result/0.1",
        "status": "installed",
        "targetStablePath": target,
        "targetIdentity": engine_result.get("targetIdentity"),
        "username": cfg["username"],
        "locale": cfg["locale"],
        "keyboard": cfg["keyboard"],
        "timezone": cfg["timezone"],
        "passwordStoredInEvidence": False,
        "sourceMediaProtected": engine_result.get("sourceMediaProtected") is True,
        "explicitConfirmationVerified": engine_result.get("explicitConfirmationVerified") is True,
    }


def self_test() -> None:
    good = {
        "targetStablePath": "/dev/disk/by-id/virtio-SWIR_TEST",
        "confirmationToken": "ERASE-SWIR-0123456789ab",
        "username": "swiruser",
        "password": "correct horse battery staple",
        "locale": "en_US.UTF-8",
        "keyboard": "us",
        "timezone": "Etc/UTC",
    }
    assert validate_request(good)["username"] == "swiruser"
    for field, value in (("targetStablePath", "/dev/sda"), ("confirmationToken", "YES"), ("username", "root"), ("password", "short"), ("keyboard", "bad layout"), ("timezone", "UTC")):
        broken = dict(good)
        broken[field] = value
        try:
            validate_request(broken)
        except InstallerError:
            pass
        else:
            raise AssertionError(f"invalid {field} was accepted")

    def expect_marker_rejected(path: pathlib.Path, *, expected_uid: int) -> None:
        try:
            load_trusted_live_marker(path, expected_uid=expected_uid)
        except InstallerError:
            return
        raise AssertionError("invalid trusted Live marker was accepted")

    with tempfile.TemporaryDirectory(prefix="swir-live-marker-selftest-") as temp_dir:
        root = pathlib.Path(temp_dir)
        marker = root / "live.json"
        expected_uid = os.getuid()

        marker.write_text(json.dumps(LIVE_MARKER_EXPECTED) + "\n", encoding="utf-8")
        os.chmod(marker, 0o444)
        assert load_trusted_live_marker(marker, expected_uid=expected_uid) == LIVE_MARKER_EXPECTED

        for field, value in (("schema", "swir.live-media/9.9"), ("mode", "installed"), ("installerAllowed", False), ("readOnlyFirst", False)):
            os.chmod(marker, 0o644)
            broken_marker = dict(LIVE_MARKER_EXPECTED)
            broken_marker[field] = value
            marker.write_text(json.dumps(broken_marker) + "\n", encoding="utf-8")
            os.chmod(marker, 0o444)
            expect_marker_rejected(marker, expected_uid=expected_uid)

        os.chmod(marker, 0o644)
        extra_marker = dict(LIVE_MARKER_EXPECTED)
        extra_marker["unexpected"] = True
        marker.write_text(json.dumps(extra_marker) + "\n", encoding="utf-8")
        os.chmod(marker, 0o444)
        expect_marker_rejected(marker, expected_uid=expected_uid)

        os.chmod(marker, 0o644)
        marker.write_text("not-json\n", encoding="utf-8")
        os.chmod(marker, 0o444)
        expect_marker_rejected(marker, expected_uid=expected_uid)

        os.chmod(marker, 0o644)
        marker.write_text("", encoding="utf-8")
        os.chmod(marker, 0o444)
        expect_marker_rejected(marker, expected_uid=expected_uid)

        os.chmod(marker, 0o644)
        marker.write_bytes(b"x" * (MAX_LIVE_MARKER_BYTES + 1))
        os.chmod(marker, 0o444)
        expect_marker_rejected(marker, expected_uid=expected_uid)

        os.chmod(marker, 0o644)
        marker.write_text(json.dumps(LIVE_MARKER_EXPECTED) + "\n", encoding="utf-8")
        os.chmod(marker, 0o666)
        expect_marker_rejected(marker, expected_uid=expected_uid)

        os.chmod(marker, 0o444)
        os.chmod(root, 0o777)
        expect_marker_rejected(marker, expected_uid=expected_uid)
        os.chmod(root, 0o700)

        if os.geteuid() == 0:
            os.chmod(marker, 0o444)
            os.chown(marker, 65534, -1)
            expect_marker_rejected(marker, expected_uid=expected_uid)
            os.chown(marker, expected_uid, -1)

        marker.unlink()
        target = root / "target.json"
        target.write_text(json.dumps(LIVE_MARKER_EXPECTED) + "\n", encoding="utf-8")
        os.chmod(target, 0o444)
        marker.symlink_to(target)
        expect_marker_rejected(marker, expected_uid=expected_uid)

    print("SWIR graphical installer helper self-test OK")


def main() -> None:
    if sys.argv[1:] == ["--self-test"]:
        self_test()
        return
    if sys.argv[1:]:
        fail("unexpected command-line arguments")
    try:
        raw = sys.stdin.read(8192)
        if not raw or len(raw) >= 8192:
            raise InstallerError("installer request is empty or too large")
        cfg = validate_request(json.loads(raw))
        ensure_live_environment()
        result = install(cfg)
        print(json.dumps(result, sort_keys=True))
    except (InstallerError, json.JSONDecodeError, subprocess.CalledProcessError, OSError) as exc:
        fail(str(exc))


if __name__ == "__main__":
    main()
