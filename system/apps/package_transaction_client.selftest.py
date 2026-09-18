#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import pathlib
import socket
import tempfile
import threading

from package_transaction_client import PackageBrokerError, PackageTransactionClient


def serve_once(path: str, responder) -> threading.Thread:
    ready = threading.Event()

    def run() -> None:
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(path)
        os.chmod(path, 0o600)
        server.listen(1)
        ready.set()
        conn, _ = server.accept()
        with conn:
            data = bytearray()
            while b"\n" not in data:
                chunk = conn.recv(4096)
                if not chunk:
                    break
                data.extend(chunk)
            request = json.loads(bytes(data).split(b"\n", 1)[0].decode("utf-8"))
            response = responder(request)
            conn.sendall((json.dumps(response, separators=(",", ":")) + "\n").encode("utf-8"))
        server.close()

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    assert ready.wait(2.0)
    return thread


with tempfile.TemporaryDirectory(prefix="swir-package-client-") as temp:
    root = pathlib.Path(temp)
    package_socket = str(root / "package.sock")
    auth_socket = str(root / "auth.sock")

    def preview_response(request):
        assert request == {
            "schema": "swir.package-transaction-broker-request/0.1",
            "action": "preview",
            "operation": "install",
            "packageName": "nano",
        }
        return {
            "schema": "swir.package-transaction-broker-response/0.1",
            "ok": True,
            "action": "preview",
            "preview": {
                "planDigest": "a" * 64,
                "packageId": "system:nano",
                "packageName": "nano",
                "operation": "install",
                "packageManager": "apt",
                "repositoryId": None,
                "commandPreview": ["apt-get", "install", "--", "nano"],
                "autoExecutable": False,
                "requiresPrivilege": True,
                "journalRequired": True,
            },
        }

    preview_thread = serve_once(package_socket, preview_response)
    client = PackageTransactionClient(package_socket=package_socket, auth_socket=auth_socket, timeout=3.0)
    preview = client.preview("install", "nano")
    preview_thread.join(2.0)
    assert preview.package_id == "system:nano"
    assert preview.plan_digest == "a" * 64
    assert preview.command_preview == ("apt-get", "install", "--", "nano")

    envelope = {
        "schema": "swir.peer-authorization-envelope/0.1",
        "payload": {"grantId": "selftest"},
        "mac": "b" * 64,
    }

    def auth_response(request):
        assert request["schema"] == "swir.peer-authorization-request/0.1"
        assert request["scope"] == "packages.mutate"
        assert request["planDigest"] == preview.plan_digest
        assert request["packageId"] == preview.package_id
        assert request["operation"] == "install"
        assert request["allowUserInteraction"] is True
        assert "uid" not in request and "pid" not in request
        return {
            "schema": "swir.peer-authorization-response/0.1",
            "authorized": True,
            "envelope": envelope,
        }

    auth_thread = serve_once(auth_socket, auth_response)
    received = client.authorize(preview)
    auth_thread.join(2.0)
    assert received == envelope

    os.unlink(package_socket)

    def commit_response(request):
        assert request["schema"] == "swir.package-transaction-broker-request/0.1"
        assert request["action"] == "commit"
        assert request["operation"] == "install"
        assert request["packageName"] == "nano"
        assert request["peerAuthorizationEnvelope"] == envelope
        assert "uid" not in request and "pid" not in request
        return {
            "schema": "swir.package-transaction-broker-response/0.1",
            "ok": True,
            "action": "commit",
            "transaction": {
                "id": "txn-selftest-0001",
                "state": "committed",
                "planDigest": preview.plan_digest,
                "packageId": preview.package_id,
                "packageName": "nano",
                "operation": "install",
            },
        }

    commit_thread = serve_once(package_socket, commit_response)
    transaction = client.commit(preview, envelope)
    commit_thread.join(2.0)
    assert transaction["state"] == "committed"
    assert transaction["planDigest"] == preview.plan_digest

    try:
        client.preview("install", "bad;package")
        raise AssertionError("unsafe package name accepted")
    except PackageBrokerError as exc:
        assert exc.code == "INVALID_PACKAGE_NAME"

print("SWIR package transaction client self-test OK")
