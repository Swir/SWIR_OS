#!/usr/bin/env python3
"""Fail-closed application-layer package mutation flow for SWIR native UIs.

This module deliberately contains no package-manager or privilege execution. It
wraps :mod:`package_transaction_client` so native GTK applications can enforce
an explicit preview -> user confirmation -> authorization -> commit sequence.
A preview is single-use: after commit is requested it cannot be replayed, even
when authorization or execution fails. The privileged broker still recomputes
and validates the plan and its signed peer-authorization envelope.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any, Final

from package_transaction_client import PackageBrokerError, PackagePreview, PackageTransactionClient

_ALLOWED_OPERATIONS: Final = frozenset({"install", "update", "remove"})


@dataclass(frozen=True)
class PackageMutationIntent:
    """Immutable preview handed to a confirmation surface."""

    preview: PackagePreview

    @property
    def confirmation_digest(self) -> str:
        return self.preview.plan_digest


class PackageMutationFlow:
    """Bind an explicit UI confirmation to exactly one broker preview."""

    def __init__(self, client: PackageTransactionClient) -> None:
        if not hasattr(client, "preview") or not hasattr(client, "authorize") or not hasattr(client, "commit"):
            raise TypeError("PackageMutationFlow requires a PackageTransactionClient-compatible object")
        self._client = client
        self._lock = threading.Lock()
        self._consumed_digests: set[str] = set()

    def available(self) -> bool:
        return bool(self._client.available())

    def prepare(self, operation: str, package_name: str) -> PackageMutationIntent:
        if operation not in _ALLOWED_OPERATIONS:
            raise PackageBrokerError("INVALID_OPERATION", "unsupported package operation")
        preview = self._client.preview(operation, package_name)
        if preview.operation != operation or preview.package_name != package_name:
            raise PackageBrokerError("PACKAGE_PREVIEW_MISMATCH", "package preview does not match the requested mutation")
        return PackageMutationIntent(preview=preview)

    def commit(self, intent: PackageMutationIntent, confirmed_digest: str) -> dict[str, Any]:
        if not isinstance(intent, PackageMutationIntent):
            raise PackageBrokerError("MUTATION_INTENT_INVALID", "package mutation intent is invalid")
        preview = intent.preview
        if confirmed_digest != preview.plan_digest:
            raise PackageBrokerError("CONFIRMATION_MISMATCH", "confirmation does not match the displayed package plan")

        # Consume before requesting Polkit so a double-click, re-entrant callback,
        # or failed authorization cannot replay the same confirmation.
        with self._lock:
            if preview.plan_digest in self._consumed_digests:
                raise PackageBrokerError("CONFIRMATION_ALREADY_USED", "package confirmation has already been consumed")
            self._consumed_digests.add(preview.plan_digest)

        envelope = self._client.authorize(preview)
        transaction = self._client.commit(preview, envelope)
        if transaction.get("planDigest") != preview.plan_digest:
            raise PackageBrokerError("PACKAGE_COMMIT_PLAN_MISMATCH", "committed transaction digest does not match confirmed preview")
        return transaction


__all__ = ["PackageMutationFlow", "PackageMutationIntent"]
