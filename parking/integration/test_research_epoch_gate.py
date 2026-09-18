from __future__ import annotations

import hashlib

import pytest

from parking.integration.project_memory_context_epoch import ProjectStateEpoch
from parking.integration.research_epoch_gate import (
    assert_same_research_scope,
    authorize_research_epoch,
    issue_research_epoch_receipt,
    validate_research_epoch_receipt,
)
from parking.integration.research_memory_bridge import issue_memory_receipt
from parking.integration.research_provenance_contract import issue_evidence


SCOPE = {
    "chat_id": "chat_a",
    "project_id": "project_a",
    "repo_scope": "owner/repo",
}
CLAIM = hashlib.sha256(b"claim").hexdigest()
FACT = hashlib.sha256(b"fact").hexdigest()


def evidence(evidence_id: str = "ev_a", *, content: str = "body") -> dict:
    return issue_evidence(
        evidence_id=evidence_id,
        chat_id=SCOPE["chat_id"],
        project_id=SCOPE["project_id"],
        repo_scope=SCOPE["repo_scope"],
        claim_digest=CLAIM,
        source_url=f"https://example.com/{evidence_id}",
        source_kind="official",
        stance="supports",
        content_digest=hashlib.sha256(content.encode()).hexdigest(),
        retrieved_at="2026-09-14T06:00:00Z",
        observed_at="2026-09-14T07:00:00Z",
    )


def memory(records: list[dict]) -> dict:
    return issue_memory_receipt(
        memory_id="memory_a",
        fact_digest=FACT,
        claim_digest=CLAIM,
        records=records,
        chat_id=SCOPE["chat_id"],
        project_id=SCOPE["project_id"],
        repo_scope=SCOPE["repo_scope"],
        observed_at="2026-09-14T07:00:00Z",
        freshness_window_seconds=86400,
    )


def test_current_epoch_authorizes_exact_provenance_and_memory() -> None:
    records = [evidence()]
    memory_receipt = memory(records)
    receipt = issue_research_epoch_receipt(
        scope=SCOPE,
        state_epoch=7,
        claim_digest=CLAIM,
        evidence_records=records,
        memory_receipt=memory_receipt,
    )
    active = ProjectStateEpoch.create(SCOPE, 7)
    authorize_research_epoch(
        receipt,
        active=active,
        evidence_records=records,
        memory_receipt=memory_receipt,
    )
    assert validate_research_epoch_receipt(receipt) == receipt


def test_epoch_change_makes_old_research_inaccessible() -> None:
    records = [evidence()]
    receipt = issue_research_epoch_receipt(
        scope=SCOPE,
        state_epoch=7,
        claim_digest=CLAIM,
        evidence_records=records,
    )
    with pytest.raises(PermissionError, match="stale research Project State epoch"):
        authorize_research_epoch(
            receipt,
            active=ProjectStateEpoch.create(SCOPE, 8),
            evidence_records=records,
        )


def test_cross_chat_project_and_repo_scope_fail_closed() -> None:
    records = [evidence()]
    receipt = issue_research_epoch_receipt(
        scope=SCOPE,
        state_epoch=7,
        claim_digest=CLAIM,
        evidence_records=records,
    )
    foreign_scopes = [
        {**SCOPE, "chat_id": "chat_b"},
        {**SCOPE, "project_id": "project_b"},
        {**SCOPE, "repo_scope": "owner/other"},
    ]
    for foreign in foreign_scopes:
        with pytest.raises(PermissionError, match="scope/epoch mismatch"):
            assert_same_research_scope(receipt, expected_scope=foreign, state_epoch=7)


def test_evidence_swap_after_receipt_fails_closed() -> None:
    original = [evidence("ev_a", content="original")]
    receipt = issue_research_epoch_receipt(
        scope=SCOPE,
        state_epoch=7,
        claim_digest=CLAIM,
        evidence_records=original,
    )
    replacement = [evidence("ev_b", content="replacement")]
    with pytest.raises(PermissionError, match="provenance changed"):
        authorize_research_epoch(
            receipt,
            active=ProjectStateEpoch.create(SCOPE, 7),
            evidence_records=replacement,
        )


def test_memory_receipt_swap_after_receipt_fails_closed() -> None:
    records = [evidence()]
    original_memory = memory(records)
    receipt = issue_research_epoch_receipt(
        scope=SCOPE,
        state_epoch=7,
        claim_digest=CLAIM,
        evidence_records=records,
        memory_receipt=original_memory,
    )
    tampered_memory = dict(original_memory)
    tampered_memory["memory_id"] = "memory_other"
    with pytest.raises(PermissionError, match="provenance changed"):
        authorize_research_epoch(
            receipt,
            active=ProjectStateEpoch.create(SCOPE, 7),
            evidence_records=records,
            memory_receipt=tampered_memory,
        )


def test_unknown_fields_and_secret_payloads_are_rejected() -> None:
    records = [evidence()]
    receipt = issue_research_epoch_receipt(
        scope=SCOPE,
        state_epoch=7,
        claim_digest=CLAIM,
        evidence_records=records,
    )
    receipt["api_key"] = "must-not-persist"
    with pytest.raises(ValueError, match="schema"):
        validate_research_epoch_receipt(receipt)


def test_epoch_receipt_does_not_expose_raw_scope_identifiers() -> None:
    records = [evidence()]
    receipt = issue_research_epoch_receipt(
        scope=SCOPE,
        state_epoch=7,
        claim_digest=CLAIM,
        evidence_records=records,
    )
    rendered = repr(receipt)
    assert SCOPE["chat_id"] not in rendered
    assert SCOPE["project_id"] not in rendered
    assert SCOPE["repo_scope"] not in rendered
