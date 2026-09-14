from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

from .builder_action_receipt import validate_builder_action_receipt
from .project_memory_context_epoch import ProjectStateEpoch
from .scope_contract import ScopeKey, parse_scope

_SHA256_HEX = set("0123456789abcdef")


def _digest(value: Any, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(ch not in _SHA256_HEX for ch in value):
        raise ValueError(f"invalid {label}")
    return value


def _epoch(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError("invalid state_epoch")
    return value


def _scope_payload(scope: ScopeKey) -> dict[str, str]:
    return {
        "chat_id": scope.chat_id,
        "project_id": scope.project_id,
        "repo_scope": scope.repo_scope,
    }


def _scope_epoch_digest(scope: ScopeKey, state_epoch: int) -> str:
    payload = {"scope": _scope_payload(scope), "state_epoch": _epoch(state_epoch)}
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _receipt_digest(receipt: Mapping[str, object]) -> str:
    encoded = json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def issue_builder_epoch_receipt(
    *,
    scope: Mapping[str, object] | ScopeKey,
    state_epoch: int,
    builder_receipt: Mapping[str, object],
) -> dict[str, object]:
    parsed = parse_scope(scope)
    epoch = _epoch(state_epoch)
    if not isinstance(builder_receipt, Mapping):
        raise ValueError("builder_receipt must be an object")

    # The existing builder receipt is validated by its own contract. We do not
    # duplicate its fields here; this adapter binds the exact validated receipt
    # to the current Project State epoch without persisting raw scope identifiers.
    builder_scope = parse_scope(builder_receipt.get("scope"))
    if builder_scope != parsed:
        raise PermissionError("builder receipt scope mismatch")

    return {
        "schema_version": 1,
        "state_epoch": epoch,
        "scope_epoch_digest": _scope_epoch_digest(parsed, epoch),
        "builder_receipt_digest": _receipt_digest(builder_receipt),
    }


def validate_builder_epoch_receipt(receipt: Mapping[str, object]) -> dict[str, object]:
    required = {
        "schema_version",
        "state_epoch",
        "scope_epoch_digest",
        "builder_receipt_digest",
    }
    if not isinstance(receipt, Mapping) or set(receipt) != required:
        raise ValueError("invalid builder epoch receipt schema")
    if receipt.get("schema_version") != 1:
        raise ValueError("unsupported builder epoch receipt schema")
    _epoch(receipt.get("state_epoch"))
    _digest(receipt.get("scope_epoch_digest"), "scope_epoch_digest")
    _digest(receipt.get("builder_receipt_digest"), "builder_receipt_digest")
    return dict(receipt)


def authorize_builder_epoch(
    receipt: Mapping[str, object],
    *,
    active: ProjectStateEpoch,
    builder_receipt: Mapping[str, object],
) -> None:
    validated = validate_builder_epoch_receipt(receipt)
    active_scope = parse_scope(active.scope)

    if validated["state_epoch"] != active.state_epoch:
        raise PermissionError("stale builder Project State epoch")
    if validated["scope_epoch_digest"] != _scope_epoch_digest(active_scope, active.state_epoch):
        raise PermissionError("builder scope/epoch mismatch")

    if not isinstance(builder_receipt, Mapping):
        raise ValueError("builder_receipt must be an object")
    builder_scope = parse_scope(builder_receipt.get("scope"))
    if builder_scope != active_scope:
        raise PermissionError("builder receipt scope mismatch")

    if validated["builder_receipt_digest"] != _receipt_digest(builder_receipt):
        raise PermissionError("builder receipt changed after epoch authorization")


def assert_same_builder_scope(
    receipt: Mapping[str, object],
    *,
    expected_scope: Mapping[str, object] | ScopeKey,
    state_epoch: int,
) -> None:
    validated = validate_builder_epoch_receipt(receipt)
    parsed = parse_scope(expected_scope)
    epoch = _epoch(state_epoch)
    if validated["state_epoch"] != epoch:
        raise PermissionError("stale builder Project State epoch")
    if validated["scope_epoch_digest"] != _scope_epoch_digest(parsed, epoch):
        raise PermissionError("builder scope/epoch mismatch")
