from __future__ import annotations

import hashlib

import pytest

from parking.integration.research_memory_bridge import (
    issue_memory_receipt,
    memory_recall_state,
    validate_memory_receipt,
)
from parking.integration.research_provenance_contract import issue_evidence


CHAT = "chat_a"
PROJECT = "project_a"
REPO = "owner/repo"
CLAIM = hashlib.sha256(b"claim").hexdigest()
FACT = hashlib.sha256(b"fact").hexdigest()


def evidence(evidence_id: str, stance: str, content: str, *, project: str = PROJECT) -> dict:
    return issue_evidence(
        evidence_id=evidence_id,
        chat_id=CHAT,
        project_id=project,
        repo_scope=REPO,
        claim_digest=CLAIM,
        source_url=f"https://example.com/{evidence_id}",
        source_kind="official",
        stance=stance,
        content_digest=hashlib.sha256(content.encode()).hexdigest(),
        retrieved_at="2026-09-02T10:00:00Z",
        observed_at="2026-09-02T12:00:00Z",
    )


def receipt(records: list[dict]) -> dict:
    return issue_memory_receipt(
        memory_id="memory_a",
        fact_digest=FACT,
        claim_digest=CLAIM,
        records=records,
        chat_id=CHAT,
        project_id=PROJECT,
        repo_scope=REPO,
        observed_at="2026-09-02T12:00:00Z",
        freshness_window_seconds=86400,
    )


def test_supported_fresh_evidence_may_answer_as_settled() -> None:
    records = [evidence("ev_support", "supports", "yes")]
    state = memory_recall_state(
        receipt(records), chat_id=CHAT, project_id=PROJECT, repo_scope=REPO,
        evidence_records=records, now="2026-09-02T12:30:00Z",
    )
    assert state == {
        "status": "supported",
        "stale": False,
        "may_answer_as_settled": True,
        "requires_source_refresh": False,
        "requires_contradiction_disclosure": False,
    }


def test_contradiction_is_preserved_and_blocks_settled_answer() -> None:
    records = [
        evidence("ev_support", "supports", "yes"),
        evidence("ev_against", "contradicts", "no"),
    ]
    state = memory_recall_state(
        receipt(records), chat_id=CHAT, project_id=PROJECT, repo_scope=REPO,
        evidence_records=records, now="2026-09-02T12:30:00Z",
    )
    assert state["status"] == "contested"
    assert state["may_answer_as_settled"] is False
    assert state["requires_contradiction_disclosure"] is True


def test_context_only_evidence_is_not_promoted_to_settled_fact() -> None:
    records = [evidence("ev_context", "context", "background")]
    state = memory_recall_state(
        receipt(records), chat_id=CHAT, project_id=PROJECT, repo_scope=REPO,
        evidence_records=records, now="2026-09-02T12:30:00Z",
    )
    assert state["status"] == "context_only"
    assert state["may_answer_as_settled"] is False


def test_stale_evidence_requires_refresh() -> None:
    records = [evidence("ev_support", "supports", "yes")]
    state = memory_recall_state(
        receipt(records), chat_id=CHAT, project_id=PROJECT, repo_scope=REPO,
        evidence_records=records, now="2026-09-04T10:00:01Z",
    )
    assert state["stale"] is True
    assert state["requires_source_refresh"] is True
    assert state["may_answer_as_settled"] is False


def test_cross_project_recall_fails_closed() -> None:
    records = [evidence("ev_support", "supports", "yes")]
    with pytest.raises(ValueError, match="scope"):
        memory_recall_state(
            receipt(records), chat_id=CHAT, project_id="project_b", repo_scope=REPO,
            evidence_records=records, now="2026-09-02T12:30:00Z",
        )


def test_evidence_set_tampering_fails_closed() -> None:
    original = [evidence("ev_support", "supports", "yes")]
    replacement = [evidence("ev_other", "supports", "different")]
    with pytest.raises(ValueError, match="evidence binding"):
        memory_recall_state(
            receipt(original), chat_id=CHAT, project_id=PROJECT, repo_scope=REPO,
            evidence_records=replacement, now="2026-09-02T12:30:00Z",
        )


def test_unknown_receipt_fields_are_rejected_including_secret_payloads() -> None:
    records = [evidence("ev_support", "supports", "yes")]
    row = receipt(records)
    row["api_key"] = "must-not-persist"
    with pytest.raises(ValueError, match="schema"):
        validate_memory_receipt(row)


def test_unbounded_freshness_is_rejected() -> None:
    records = [evidence("ev_support", "supports", "yes")]
    with pytest.raises(ValueError, match="out of bounds"):
        issue_memory_receipt(
            memory_id="memory_a",
            fact_digest=FACT,
            claim_digest=CLAIM,
            records=records,
            chat_id=CHAT,
            project_id=PROJECT,
            repo_scope=REPO,
            observed_at="2026-09-02T12:00:00Z",
            freshness_window_seconds=10 * 366 * 24 * 60 * 60,
        )
