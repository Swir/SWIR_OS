#!/usr/bin/env python3
"""Unprivileged client for SWIR package preview -> Polkit -> commit flow.

The client never executes apt/dpkg/pkexec itself and never sends a caller-supplied
Unix uid/pid. Identity is established by the existing peer-authorization broker
from SO_PEERCRED and systemd-logind; the privileged package broker consumes the
short-lived signed authorization envelope.
"""

from __future__ import annotations

import json
import os
import re
import socket
import stat
from dataclasses import dataclass
from typing import Any, Final

PACKAGE_SOCKET: Final = "/run/swir/package-transaction.sock"
AUTH_SOCKET: Final = "/run/swir/peer-authorization.sock"
PACKAGE_REQUEST_SCHEMA: Final = "swir.package-transaction-broker-request/0.1"
PACKAGE_RESPONSE_SCHEMA: Final = "swir.package-transaction-broker-response/0.1"
AUTH_REQUEST_SCHEMA: Final = "swir.peer-authorization-request/0.1"
AUTH_RESPONSE_SCHEMA: Final = "swir.peer-authorization-response/0.1"
MAX_WIRE_BYTES: Final = 64 * 1024
PACKAGE_RE: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9+._:@-]{0,127}$")
DIGEST_RE: Final = re.compile(r"^[a-f0-9]{64}$")
OPERATIONS: Final = frozenset({"install", "update", "remove"})


class PackageBrokerError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class PackagePreview:
    operation: str
    package_name: str
    package_id: str
    plan_digest: str
    package_manager: str
    command_preview: tuple[str, ...]


def _validate_socket_path(path: str) -> str:
    if not isinstance(path, str) or not path.startswith("/") or "\x00" in path:
        raise PackageBrokerError("SOCKET_PATH_INVALID", "broker socket path must be absolute")
    return path


def _socket_available(path: str) -> bool:
    try:
        info = os.lstat(path)
    except OSError:
        return False
    return stat.S_ISSOCK(info.st_mode) and not stat.S_ISLNK(info.st_mode)


def _read_json_line(sock: socket.socket) -> dict[str, Any]:
    data = bytearray()
    while len(data) <= MAX_WIRE_BYTES:
        chunk = sock.recv(min(4096, MAX_WIRE_BYTES + 1 - len(data)))
        if not chunk:
            break
        data.extend(chunk)
        if b"\n" in chunk:
            break
    if len(data) > MAX_WIRE_BYTES:
        raise PackageBrokerError("RESPONSE_TOO_LARGE", "broker response exceeded size limit")
    if b"\n" not in data:
        raise PackageBrokerError("RESPONSE_TERMINATOR_MISSING", "broker response was not newline terminated")
    line, trailing = bytes(data).split(b"\n", 1)
    if trailing.strip():
        raise PackageBrokerError("MULTIPLE_RESPONSES", "broker returned more than one response")
    try:
        value = json.loads(line.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PackageBrokerError("RESPONSE_INVALID_JSON", "broker response is invalid JSON") from exc
    if not isinstance(value, dict):
        raise PackageBrokerError("RESPONSE_INVALID", "broker response must be an object")
    return value


def _request(socket_path: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
    wire = (json.dumps(payload, separators=(",", ":"), sort_keys=True) + "\n").encode("utf-8")
    if len(wire) > MAX_WIRE_BYTES:
        raise PackageBrokerError("REQUEST_TOO_LARGE", "broker request exceeded size limit")
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        sock.connect(socket_path)
        sock.sendall(wire)
        return _read_json_line(sock)
    except (OSError, TimeoutError) as exc:
        raise PackageBrokerError("BROKER_UNAVAILABLE", f"broker unavailable: {exc}") from exc
    finally:
        sock.close()


def _safe_package_name(value: str) -> str:
    if not isinstance(value, str) or PACKAGE_RE.fullmatch(value) is None:
        raise PackageBrokerError("INVALID_PACKAGE_NAME", "invalid package name")
    return value


class PackageTransactionClient:
    def __init__(
        self,
        package_socket: str = PACKAGE_SOCKET,
        auth_socket: str = AUTH_SOCKET,
        timeout: float = 40.0,
    ) -> None:
        self.package_socket = _validate_socket_path(package_socket)
        self.auth_socket = _validate_socket_path(auth_socket)
        if not 1.0 <= timeout <= 120.0:
            raise PackageBrokerError("INVALID_TIMEOUT", "timeout must be between 1 and 120 seconds")
        self.timeout = timeout

    def available(self) -> bool:
        return _socket_available(self.package_socket) and _socket_available(self.auth_socket)

    def preview(self, operation: str, package_name: str) -> PackagePreview:
        if operation not in OPERATIONS:
            raise PackageBrokerError("INVALID_OPERATION", "unsupported package operation")
        package_name = _safe_package_name(package_name)
        response = _request(
            self.package_socket,
            {
                "schema": PACKAGE_REQUEST_SCHEMA,
                "action": "preview",
                "operation": operation,
                "packageName": package_name,
            },
            self.timeout,
        )
        if response.get("schema") != PACKAGE_RESPONSE_SCHEMA:
            raise PackageBrokerError("PACKAGE_RESPONSE_SCHEMA_INVALID", "package broker response schema is invalid")
        if response.get("ok") is not True:
            error = response.get("error") if isinstance(response.get("error"), dict) else {}
            raise PackageBrokerError(str(error.get("code") or "PACKAGE_PREVIEW_FAILED"), str(error.get("message") or "package preview failed"))
        preview = response.get("preview")
        if not isinstance(preview, dict):
            raise PackageBrokerError("PACKAGE_PREVIEW_INVALID", "package preview is missing")
        digest = preview.get("planDigest")
        package_id = preview.get("packageId")
        command = preview.get("commandPreview")
        if not isinstance(digest, str) or DIGEST_RE.fullmatch(digest) is None:
            raise PackageBrokerError("PACKAGE_PREVIEW_INVALID", "package preview digest is invalid")
        if not isinstance(package_id, str) or not package_id.startswith("system:"):
            raise PackageBrokerError("PACKAGE_PREVIEW_INVALID", "package preview id is invalid")
        if preview.get("packageName") != package_name or preview.get("operation") != operation:
            raise PackageBrokerError("PACKAGE_PREVIEW_MISMATCH", "package preview does not match the request")
        if not isinstance(command, list) or not command or not all(isinstance(item, str) and item for item in command):
            raise PackageBrokerError("PACKAGE_PREVIEW_INVALID", "package command preview is invalid")
        return PackagePreview(
            operation=operation,
            package_name=package_name,
            package_id=package_id,
            plan_digest=digest,
            package_manager=str(preview.get("packageManager") or ""),
            command_preview=tuple(command),
        )

    def authorize(self, preview: PackagePreview) -> dict[str, Any]:
        response = _request(
            self.auth_socket,
            {
                "schema": AUTH_REQUEST_SCHEMA,
                "scope": "packages.mutate",
                "planDigest": preview.plan_digest,
                "packageId": preview.package_id,
                "operation": preview.operation,
                "allowUserInteraction": True,
            },
            self.timeout,
        )
        if response.get("schema") != AUTH_RESPONSE_SCHEMA:
            raise PackageBrokerError("AUTH_RESPONSE_SCHEMA_INVALID", "authorization broker response schema is invalid")
        if response.get("authorized") is not True:
            error = response.get("error") if isinstance(response.get("error"), dict) else {}
            code = str(error.get("code") or "AUTHORIZATION_DENIED")
            message = str(error.get("message") or "package authorization was denied")
            raise PackageBrokerError(code, message)
        envelope = response.get("envelope")
        if not isinstance(envelope, dict) or envelope.get("schema") != "swir.peer-authorization-envelope/0.1":
            raise PackageBrokerError("AUTH_ENVELOPE_INVALID", "authorization broker did not return a valid envelope")
        return envelope

    def commit(self, preview: PackagePreview, envelope: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(envelope, dict):
            raise PackageBrokerError("AUTH_ENVELOPE_INVALID", "authorization envelope must be an object")
        response = _request(
            self.package_socket,
            {
                "schema": PACKAGE_REQUEST_SCHEMA,
                "action": "commit",
                "operation": preview.operation,
                "packageName": preview.package_name,
                "peerAuthorizationEnvelope": envelope,
            },
            self.timeout,
        )
        if response.get("schema") != PACKAGE_RESPONSE_SCHEMA:
            raise PackageBrokerError("PACKAGE_RESPONSE_SCHEMA_INVALID", "package broker response schema is invalid")
        if response.get("ok") is not True:
            error = response.get("error") if isinstance(response.get("error"), dict) else {}
            raise PackageBrokerError(str(error.get("code") or "PACKAGE_COMMIT_FAILED"), str(error.get("message") or "package transaction failed"))
        transaction = response.get("transaction")
        if not isinstance(transaction, dict) or transaction.get("state") != "committed":
            raise PackageBrokerError("PACKAGE_COMMIT_INCOMPLETE", "package transaction did not reach committed state")
        if transaction.get("planDigest") != preview.plan_digest:
            raise PackageBrokerError("PACKAGE_COMMIT_PLAN_MISMATCH", "committed transaction digest does not match preview")
        return transaction

    def authorize_and_commit(self, preview: PackagePreview) -> dict[str, Any]:
        return self.commit(preview, self.authorize(preview))


__all__ = [
    "PackageBrokerError",
    "PackagePreview",
    "PackageTransactionClient",
]
