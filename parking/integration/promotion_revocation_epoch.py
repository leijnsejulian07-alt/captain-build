from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass

MAX_EPOCH = 2**63 - 1
SCOPE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
REASONS = {"project_reset", "repo_rebind", "session_revoke", "security_reset", "manual"}


def _need_id(name: str, value: object) -> str:
    if not isinstance(value, str) or not SCOPE_ID_RE.fullmatch(value):
        raise ValueError(f"invalid {name}")
    return value


def _need_epoch(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1 or value > MAX_EPOCH:
        raise ValueError("invalid security epoch")
    return value


def _scope_key(chat_id: str, project_id: str, repo_scope_hash: str) -> str:
    chat = _need_id("chat_id", chat_id)
    project = _need_id("project_id", project_id)
    if not isinstance(repo_scope_hash, str) or not DIGEST_RE.fullmatch(repo_scope_hash):
        raise ValueError("invalid repo scope hash")
    payload = json.dumps([chat, project, repo_scope_hash], separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class EpochSnapshot:
    scope_key: str
    epoch: int


class InMemoryPromotionEpochStore:
    """Reference contract only. Production integration needs an atomic durable store."""

    def __init__(self) -> None:
        self._epochs: dict[str, int] = {}

    def snapshot(self, *, chat_id: str, project_id: str, repo_scope_hash: str) -> EpochSnapshot:
        key = _scope_key(chat_id, project_id, repo_scope_hash)
        epoch = self._epochs.get(key, 1)
        return EpochSnapshot(scope_key=key, epoch=epoch)

    def rotate(self, *, chat_id: str, project_id: str, repo_scope_hash: str, expected_epoch: int, reason: str) -> EpochSnapshot:
        if reason not in REASONS:
            raise ValueError("invalid revocation reason")
        expected = _need_epoch(expected_epoch)
        key = _scope_key(chat_id, project_id, repo_scope_hash)
        current = self._epochs.get(key, 1)
        if current != expected:
            raise PermissionError("security epoch changed before rotation")
        if current >= MAX_EPOCH:
            raise OverflowError("security epoch exhausted")
        next_epoch = current + 1
        self._epochs[key] = next_epoch
        return EpochSnapshot(scope_key=key, epoch=next_epoch)


def bind_receipt_epoch(receipt: dict, snapshot: EpochSnapshot) -> dict:
    """Return a copy of a just-issued receipt bound to the current scope security epoch."""
    if not isinstance(receipt, dict):
        raise ValueError("receipt required")
    if "security_epoch" in receipt or "security_scope_key" in receipt:
        raise ValueError("receipt already carries security epoch fields")
    epoch = _need_epoch(snapshot.epoch)
    if not isinstance(snapshot.scope_key, str) or not DIGEST_RE.fullmatch(snapshot.scope_key):
        raise ValueError("invalid security scope key")
    bound = dict(receipt)
    bound["security_scope_key"] = snapshot.scope_key
    bound["security_epoch"] = epoch
    return bound


def assert_receipt_epoch_current(receipt: dict, snapshot: EpochSnapshot) -> None:
    """Fail closed if a receipt predates a scope reset/rebind/revocation."""
    if not isinstance(receipt, dict):
        raise ValueError("receipt required")
    if set(receipt).isdisjoint({"security_scope_key", "security_epoch"}):
        raise PermissionError("legacy receipt is not revocation-bound")
    if receipt.get("security_scope_key") != snapshot.scope_key:
        raise PermissionError("receipt security scope mismatch")
    if _need_epoch(receipt.get("security_epoch")) != _need_epoch(snapshot.epoch):
        raise PermissionError("receipt security epoch is stale")
