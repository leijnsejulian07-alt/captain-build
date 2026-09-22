from __future__ import annotations

import hashlib

import pytest

from parking.integration.builder_action_receipt import issue_builder_action_receipt
from parking.integration.builder_epoch_gate import (
    assert_same_builder_scope,
    authorize_builder_epoch,
    issue_builder_epoch_receipt,
    validate_builder_epoch_receipt,
)
from parking.integration.project_memory_context_epoch import ProjectStateEpoch

SCOPE = {
    "chat_id": "chat_a",
    "project_id": "project_a",
    "repo_scope": "owner/repo",
}


def digest(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def builder_receipt() -> dict[str, object]:
    return issue_builder_action_receipt(
        chat_id=SCOPE["chat_id"],
        project_id=SCOPE["project_id"],
        repo_scope=SCOPE["repo_scope"],
        request_id="req_a",
        action="tests",
        session_binding=digest("session"),
        context_binding=digest("context"),
        before_state_digest=digest("before"),
        after_state_digest=digest("after"),
        artifact_digest=digest("artifact"),
        result="succeeded",
        started_at="2026-09-14T07:00:00Z",
        finished_at="2026-09-14T07:00:01Z",
    )


def test_current_epoch_authorizes_exact_builder_receipt() -> None:
    action = builder_receipt()
    receipt = issue_builder_epoch_receipt(scope=SCOPE, state_epoch=9, builder_receipt=action)
    authorize_builder_epoch(
        receipt,
        active=ProjectStateEpoch.create(SCOPE, 9),
        builder_receipt=action,
    )
    assert validate_builder_epoch_receipt(receipt) == receipt


def test_epoch_change_makes_builder_receipt_inaccessible() -> None:
    action = builder_receipt()
    receipt = issue_builder_epoch_receipt(scope=SCOPE, state_epoch=9, builder_receipt=action)
    with pytest.raises(PermissionError, match="stale builder Project State epoch"):
        authorize_builder_epoch(
            receipt,
            active=ProjectStateEpoch.create(SCOPE, 10),
            builder_receipt=action,
        )


def test_cross_chat_project_and_repo_scope_fail_closed() -> None:
    receipt = issue_builder_epoch_receipt(scope=SCOPE, state_epoch=9, builder_receipt=builder_receipt())
    foreign_scopes = [
        {**SCOPE, "chat_id": "chat_b"},
        {**SCOPE, "project_id": "project_b"},
        {**SCOPE, "repo_scope": "owner/other"},
    ]
    for foreign in foreign_scopes:
        with pytest.raises(PermissionError, match="scope/epoch mismatch"):
            assert_same_builder_scope(receipt, expected_scope=foreign, state_epoch=9)


def test_builder_receipt_swap_after_authorization_fails_closed() -> None:
    action = builder_receipt()
    receipt = issue_builder_epoch_receipt(scope=SCOPE, state_epoch=9, builder_receipt=action)
    swapped = dict(action)
    swapped["artifact_digest"] = digest("different-artifact")
    with pytest.raises(PermissionError, match="changed after epoch authorization"):
        authorize_builder_epoch(
            receipt,
            active=ProjectStateEpoch.create(SCOPE, 9),
            builder_receipt=swapped,
        )


def test_builder_receipt_scope_must_match_gate_scope() -> None:
    action = builder_receipt()
    with pytest.raises(PermissionError, match="builder receipt scope mismatch"):
        issue_builder_epoch_receipt(
            scope={**SCOPE, "project_id": "project_b"},
            state_epoch=9,
            builder_receipt=action,
        )


def test_unknown_fields_and_secret_payloads_are_rejected() -> None:
    receipt = issue_builder_epoch_receipt(scope=SCOPE, state_epoch=9, builder_receipt=builder_receipt())
    receipt["api_key"] = "must-not-persist"
    with pytest.raises(ValueError, match="schema"):
        validate_builder_epoch_receipt(receipt)


def test_epoch_receipt_does_not_expose_raw_scope_identifiers() -> None:
    receipt = issue_builder_epoch_receipt(scope=SCOPE, state_epoch=9, builder_receipt=builder_receipt())
    rendered = repr(receipt)
    assert SCOPE["chat_id"] not in rendered
    assert SCOPE["project_id"] not in rendered
    assert SCOPE["repo_scope"] not in rendered
