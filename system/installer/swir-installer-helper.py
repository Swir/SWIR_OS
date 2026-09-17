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
MAX_PASSWORD_BYTES = 256
USERNAME_RE = re.compile(r"^[a-z_][a-z0-9_-]{0,30}$")
LOCALE_RE = re.compile(r"^[A-Za-z]{2,3}(?:_[A-Za-z]{2})?(?:\.[A-Za-z0-9_-]+)?$")
KEYBOARD_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
TIMEZONE_RE = re.compile(r"^[A-Za-z0-9_+.-]+(?:/[A-Za-z0-9_+.-]+)+$")


class InstallerError(RuntimeError):
    pass


def fail(message: str, code: int = 2) -> NoReturn:
    print(json.dumps({"schema": "swir.graphical-installer-result/0.1", "status": "error", "message": message}), file=sys.stdout)
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


def ensure_live_environment() -> None:
    if os.geteuid() != 0:
        raise InstallerError("helper requires root privileges")
    if not ENGINE.is_file() or ENGINE.is_symlink() or not os.access(ENGINE, os.X_OK):
        raise InstallerError("trusted install engine is unavailable")
    st = ENGINE.stat()
    if st.st_uid != 0 or stat.S_IMODE(st.st_mode) & 0o022:
        raise InstallerError("install engine ownership/mode is unsafe")
    if not LIVE_MARKER.is_file() or LIVE_MARKER.is_symlink():
        raise InstallerError("graphical installation is allowed only from verified Live media")


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
