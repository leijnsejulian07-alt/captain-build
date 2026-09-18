from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

from .project_memory_context_epoch import ProjectStateEpoch
from .research_memory_bridge import validate_memory_receipt
from .research_provenance_contract import bind_claim_evidence, validate_evidence
from .scope_contract import ScopeKey, assert_same_scope, parse_scope

SHA256_HEX = set("0123456789abcdef")


def _digest(value: Any, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(ch not in SHA256_HEX for ch in value):
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
    payload = {
        "scope": _scope_payload(scope),
        "state_epoch": _epoch(state_epoch),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _record_set_digest(records: list[dict]) -> str:
    validated = [validate_evidence(record) for record in records]
    normalized = sorted(
        (
            {
                "evidence_id": row["evidence_id"],
                "claim_digest": row["claim_digest"],
                "content_digest": row["content_digest"],
                "scope_digest": row["scope_digest"],
                "source_url": row["source_url"],
            }
            for row in validated
        ),
        key=lambda row: row["evidence_id"],
    )
    payload = json.dumps(normalized, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def issue_research_epoch_receipt(
    *,
    scope: Mapping[str, object] | ScopeKey,
    state_epoch: int,
    claim_digest: str,
    evidence_records: list[dict],
    memory_receipt: dict | None = None,
) -> dict:
    parsed = parse_scope(scope)
    epoch = _epoch(state_epoch)
    claim = _digest(claim_digest, "claim_digest")
    if not isinstance(evidence_records, list) or not evidence_records:
        raise ValueError("evidence_records must be non-empty")

    binding = bind_claim_evidence(
        claim_digest=claim,
        records=evidence_records,
        chat_id=parsed.chat_id,
        project_id=parsed.project_id,
        repo_scope=parsed.repo_scope,
    )
    memory_digest = None
    if memory_receipt is not None:
        validated_memory = validate_memory_receipt(memory_receipt)
        if validated_memory["scope_digest"] != binding["scope_digest"]:
            raise ValueError("memory scope does not match research evidence")
        if validated_memory["claim_digest"] != claim:
            raise ValueError("memory claim does not match research evidence")
        if validated_memory["evidence_set_digest"] != binding["evidence_set_digest"]:
            raise ValueError("memory evidence binding does not match research evidence")
        memory_payload = json.dumps(validated_memory, sort_keys=True, separators=(",", ":")).encode("utf-8")
        memory_digest = hashlib.sha256(memory_payload).hexdigest()

    return {
        "schema_version": 1,
        "scope_epoch_digest": _scope_epoch_digest(parsed, epoch),
        "state_epoch": epoch,
        "claim_digest": claim,
        "evidence_set_digest": binding["evidence_set_digest"],
        "evidence_records_digest": _record_set_digest(evidence_records),
        "memory_receipt_digest": memory_digest,
    }


def validate_research_epoch_receipt(receipt: dict) -> dict:
    if not isinstance(receipt, dict):
        raise ValueError("research epoch receipt must be an object")
    required = {
        "schema_version",
        "scope_epoch_digest",
        "state_epoch",
        "claim_digest",
        "evidence_set_digest",
        "evidence_records_digest",
        "memory_receipt_digest",
    }
    if set(receipt) != required or receipt.get("schema_version") != 1:
        raise ValueError("invalid research epoch receipt schema")
    for key in ("scope_epoch_digest", "claim_digest", "evidence_set_digest", "evidence_records_digest"):
        _digest(receipt[key], key)
    _epoch(receipt["state_epoch"])
    if receipt["memory_receipt_digest"] is not None:
        _digest(receipt["memory_receipt_digest"], "memory_receipt_digest")
    return dict(receipt)


def authorize_research_epoch(
    receipt: dict,
    *,
    active: ProjectStateEpoch,
    evidence_records: list[dict],
    memory_receipt: dict | None = None,
) -> None:
    validated = validate_research_epoch_receipt(receipt)
    active_scope = parse_scope(active.scope)
    if validated["state_epoch"] != active.state_epoch:
        raise PermissionError("stale research Project State epoch")
    if validated["scope_epoch_digest"] != _scope_epoch_digest(active_scope, active.state_epoch):
        raise PermissionError("research scope/epoch mismatch")

    rebuilt = issue_research_epoch_receipt(
        scope=active_scope,
        state_epoch=active.state_epoch,
        claim_digest=validated["claim_digest"],
        evidence_records=evidence_records,
        memory_receipt=memory_receipt,
    )
    if rebuilt != validated:
        raise PermissionError("research provenance changed after authorization receipt")


def assert_same_research_scope(
    receipt: dict,
    *,
    expected_scope: Mapping[str, object] | ScopeKey,
    state_epoch: int,
) -> None:
    validated = validate_research_epoch_receipt(receipt)
    parsed = parse_scope(expected_scope)
    expected_epoch = ProjectStateEpoch.create(parsed, state_epoch)
    if validated["state_epoch"] != expected_epoch.state_epoch:
        raise PermissionError("stale research Project State epoch")
    expected_digest = _scope_epoch_digest(expected_epoch.scope, expected_epoch.state_epoch)
    if validated["scope_epoch_digest"] != expected_digest:
        raise PermissionError("research scope/epoch mismatch")
