#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from package_mutation_flow import PackageMutationFlow
from package_transaction_client import PackageBrokerError, PackagePreview


class FakeClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self.enabled = True

    def available(self) -> bool:
        return self.enabled

    def preview(self, operation: str, package_name: str) -> PackagePreview:
        self.calls.append(("preview", f"{operation}:{package_name}"))
        digest = hashlib.sha256(f"{operation}:{package_name}".encode()).hexdigest()
        return PackagePreview(
            operation=operation,
            package_name=package_name,
            package_id=f"system:{package_name}",
            plan_digest=digest,
            package_manager="apt",
            command_preview=("/usr/bin/apt-get", "--", operation, package_name),
        )

    def authorize(self, preview: PackagePreview) -> dict:
        self.calls.append(("authorize", preview.plan_digest))
        return {"schema": "swir.peer-authorization-envelope/0.1", "digest": preview.plan_digest}

    def commit(self, preview: PackagePreview, envelope: dict) -> dict:
        assert envelope["digest"] == preview.plan_digest
        self.calls.append(("commit", preview.plan_digest))
        return {"id": "txn-12345678", "state": "committed", "planDigest": preview.plan_digest}


def expect_error(code: str, fn) -> None:
    try:
        fn()
    except PackageBrokerError as exc:
        assert exc.code == code, (exc.code, code)
    else:
        raise AssertionError(f"expected {code}")


def main() -> None:
    client = FakeClient()
    flow = PackageMutationFlow(client)
    assert flow.available() is True

    intent = flow.prepare("install", "nano")
    assert intent.preview.package_name == "nano"
    assert client.calls == [("preview", "install:nano")]

    expect_error("CONFIRMATION_MISMATCH", lambda: flow.commit(intent, "0" * 64))
    assert client.calls == [("preview", "install:nano")], "mismatched confirmation must not authorize"

    transaction = flow.commit(intent, intent.confirmation_digest)
    assert transaction["state"] == "committed"
    assert [name for name, _ in client.calls] == ["preview", "authorize", "commit"]

    expect_error("CONFIRMATION_ALREADY_USED", lambda: flow.commit(intent, intent.confirmation_digest))
    assert [name for name, _ in client.calls] == ["preview", "authorize", "commit"], "single-use preview replayed"

    expect_error("INVALID_OPERATION", lambda: flow.prepare("upgrade-all", "nano"))
    client.enabled = False
    assert flow.available() is False
    print("package mutation UI flow self-test: OK")


if __name__ == "__main__":
    main()
