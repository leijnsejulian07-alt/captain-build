from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from .research_provenance_contract import bind_claim_evidence, validate_evidence

MIN_FRESHNESS_SECONDS = 60 * 60
MAX_FRESHNESS_SECONDS = 366 * 24 * 60 * 60
ALLOWED_MEMORY_STATUS = {"supported", "contested", "context_only"}


def _timestamp(value: Any, label: str) -> datetime:
    if not isinstance(value, str) or len(value) > 40:
        raise ValueError(f"invalid {label}")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"invalid {label}") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{label} must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def issue_memory_receipt(
    *,
    memory_id: str,
    fact_digest: str,
    claim_digest: str,
    records: list[dict],
    chat_id: str,
    project_id: str,
    repo_scope: str,
    observed_at: str,
    freshness_window_seconds: int,
) -> dict:
    if not isinstance(memory_id, str) or not memory_id or len(memory_id) > 128:
        raise ValueError("invalid memory_id")
    if not isinstance(fact_digest, str) or len(fact_digest) != 64 or any(ch not in "0123456789abcdef" for ch in fact_digest):
        raise ValueError("invalid fact_digest")
    if not isinstance(freshness_window_seconds, int) or isinstance(freshness_window_seconds, bool):
        raise ValueError("invalid freshness_window_seconds")
    if not MIN_FRESHNESS_SECONDS <= freshness_window_seconds <= MAX_FRESHNESS_SECONDS:
        raise ValueError("freshness_window_seconds out of bounds")

    observed = _timestamp(observed_at, "observed_at")
    binding = bind_claim_evidence(
        claim_digest=claim_digest,
        records=records,
        chat_id=chat_id,
        project_id=project_id,
        repo_scope=repo_scope,
    )

    retrieved = []
    for record in records:
        validated = validate_evidence(record)
        retrieved.append(_timestamp(validated["retrieved_at"], "retrieved_at"))
    freshest = max(retrieved)
    if freshest > observed:
        raise ValueError("evidence cannot be newer than observed_at")

    if binding["has_contradiction"]:
        status = "contested"
    elif binding["has_support"]:
        status = "supported"
    else:
        status = "context_only"

    return {
        "schema_version": 1,
        "memory_id": memory_id,
        "scope_digest": binding["scope_digest"],
        "claim_digest": binding["claim_digest"],
        "fact_digest": fact_digest,
        "evidence_set_digest": binding["evidence_set_digest"],
        "evidence_count": binding["evidence_count"],
        "status": status,
        "freshest_retrieved_at": _iso(freshest),
        "stale_after": _iso(freshest + timedelta(seconds=freshness_window_seconds)),
    }


def validate_memory_receipt(receipt: dict) -> dict:
    if not isinstance(receipt, dict):
        raise ValueError("memory receipt must be an object")
    required = {
        "schema_version", "memory_id", "scope_digest", "claim_digest", "fact_digest",
        "evidence_set_digest", "evidence_count", "status", "freshest_retrieved_at", "stale_after",
    }
    if set(receipt) != required or receipt.get("schema_version") != 1:
        raise ValueError("invalid memory receipt schema")
    if not isinstance(receipt["memory_id"], str) or not receipt["memory_id"] or len(receipt["memory_id"]) > 128:
        raise ValueError("invalid memory_id")
    for key in ("scope_digest", "claim_digest", "fact_digest", "evidence_set_digest"):
        value = receipt[key]
        if not isinstance(value, str) or len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value):
            raise ValueError(f"invalid {key}")
    if not isinstance(receipt["evidence_count"], int) or isinstance(receipt["evidence_count"], bool) or receipt["evidence_count"] < 1:
        raise ValueError("invalid evidence_count")
    if receipt["status"] not in ALLOWED_MEMORY_STATUS:
        raise ValueError("invalid memory status")
    freshest = _timestamp(receipt["freshest_retrieved_at"], "freshest_retrieved_at")
    stale_after = _timestamp(receipt["stale_after"], "stale_after")
    if stale_after <= freshest:
        raise ValueError("stale_after must follow freshest_retrieved_at")
    if (stale_after - freshest).total_seconds() > MAX_FRESHNESS_SECONDS:
        raise ValueError("memory freshness window exceeds maximum")
    return dict(receipt)


def assert_memory_access(
    receipt: dict,
    *,
    chat_id: str,
    project_id: str,
    repo_scope: str,
    evidence_records: list[dict],
) -> None:
    validated = validate_memory_receipt(receipt)
    binding = bind_claim_evidence(
        claim_digest=validated["claim_digest"],
        records=evidence_records,
        chat_id=chat_id,
        project_id=project_id,
        repo_scope=repo_scope,
    )
    if validated["scope_digest"] != binding["scope_digest"]:
        raise ValueError("memory scope mismatch")
    if validated["evidence_set_digest"] != binding["evidence_set_digest"]:
        raise ValueError("memory evidence binding mismatch")
    if validated["evidence_count"] != binding["evidence_count"]:
        raise ValueError("memory evidence count mismatch")


def memory_recall_state(
    receipt: dict,
    *,
    chat_id: str,
    project_id: str,
    repo_scope: str,
    evidence_records: list[dict],
    now: str,
) -> dict:
    assert_memory_access(
        receipt,
        chat_id=chat_id,
        project_id=project_id,
        repo_scope=repo_scope,
        evidence_records=evidence_records,
    )
    validated = validate_memory_receipt(receipt)
    current = _timestamp(now, "now")
    stale_after = _timestamp(validated["stale_after"], "stale_after")
    return {
        "status": validated["status"],
        "stale": current > stale_after,
        "may_answer_as_settled": validated["status"] == "supported" and current <= stale_after,
        "requires_source_refresh": current > stale_after,
        "requires_contradiction_disclosure": validated["status"] == "contested",
    }
