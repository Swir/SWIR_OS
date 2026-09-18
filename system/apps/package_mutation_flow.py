#!/usr/bin/env python3
"""Fail-closed application-layer package mutation flow for SWIR native UIs.

This module deliberately contains no package-manager or privilege execution. It
wraps :mod:`package_transaction_client` so native GTK applications can enforce
an explicit preview -> user confirmation -> authorization -> commit sequence.
Each prepared confirmation intent is single-use: after commit is requested that
intent cannot be replayed, even when authorization or execution fails. A fresh
preview of an unchanged plan creates a fresh intent and may be confirmed again.
The privileged broker still recomputes and validates the plan and its signed
peer-authorization envelope.
"""

from __future__ import annotations

import secrets
import threading
from dataclasses import dataclass, field
from typing import Any, Final

from package_transaction_client import PackageBrokerError, PackagePreview, PackageTransactionClient

_ALLOWED_OPERATIONS: Final = frozenset({"install", "update", "remove"})


@dataclass(frozen=True)
class PackageMutationIntent:
    """Immutable preview handed to one confirmation surface."""

    preview: PackagePreview
    _single_use_token: str = field(default_factory=lambda: secrets.token_urlsafe(24), repr=False, compare=False)

    @property
    def confirmation_digest(self) -> str:
        return self.preview.plan_digest


class PackageMutationFlow:
    """Bind an explicit UI confirmation to exactly one broker preview intent."""

    def __init__(self, client: PackageTransactionClient) -> None:
        if not hasattr(client, "preview") or not hasattr(client, "authorize") or not hasattr(client, "commit"):
            raise TypeError("PackageMutationFlow requires a PackageTransactionClient-compatible object")
        self._client = client
        self._lock = threading.Lock()
        self._consumed_tokens: set[str] = set()

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

        # Consume the intent before requesting Polkit so a double-click,
        # re-entrant callback or failed authorization cannot replay the same
        # confirmation. A newly prepared intent remains eligible even when its
        # plan digest is unchanged.
        with self._lock:
            if intent._single_use_token in self._consumed_tokens:
                raise PackageBrokerError("CONFIRMATION_ALREADY_USED", "package confirmation intent has already been consumed")
            self._consumed_tokens.add(intent._single_use_token)

        envelope = self._client.authorize(preview)
        transaction = self._client.commit(preview, envelope)
        if transaction.get("planDigest") != preview.plan_digest:
            raise PackageBrokerError("PACKAGE_COMMIT_PLAN_MISMATCH", "committed transaction digest does not match confirmed preview")
        return transaction


__all__ = ["PackageMutationFlow", "PackageMutationIntent"]
