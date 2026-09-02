from __future__ import annotations

import copy
import hashlib

import pytest

from parking.integration.builder_session_contract import authorize_builder_action, issue_builder_session

CHAT = "chat_a"
PROJECT = "project_a"
REPO = "owner/repo#feature"
SESSION = "builder_a"
HEAD = "a" * 40
WORKTREE = hashlib.sha256(b"worktree").hexdigest()
CAPS = ["diff_read", "file_read", "preview_open", "rollback", "test_run"]


def session(**overrides: object) -> dict[str, object]:
    values = {
        "chat_id": CHAT, "project_id": PROJECT, "repo_scope": REPO, "session_id": SESSION,
        "repo_head": HEAD, "worktree_digest": WORKTREE, "state_epoch": 7,
        "capabilities": CAPS, "created_at": "2026-09-02T13:00:00Z", "expires_at": "2026-09-02T17:00:00Z",
    }
    values.update(overrides)
    return issue_builder_session(**values)


def authorize(row: dict[str, object], **overrides: object) -> dict[str, object]:
    values = {
        "chat_id": CHAT, "project_id": PROJECT, "repo_scope": REPO, "session_id": SESSION,
        "repo_head": HEAD, "worktree_digest": WORKTREE, "state_epoch": 7,
        "capability": "preview_open", "now": "2026-09-02T14:00:00Z",
    }
    values.update(overrides)
    return authorize_builder_action(row, **values)


def test_exact_scope_and_workspace_authorize() -> None:
    assert authorize(session())["session_id"] == SESSION


def test_cross_project_preview_replay_fails_closed() -> None:
    with pytest.raises(PermissionError, match="scope"):
        authorize(session(), project_id="project_b")


def test_cross_repo_preview_replay_fails_closed() -> None:
    with pytest.raises(PermissionError, match="scope"):
        authorize(session(), repo_scope="owner/other#feature")


def test_changed_head_or_worktree_invalidates_session() -> None:
    with pytest.raises(PermissionError, match="workspace changed"):
        authorize(session(), repo_head="b" * 40)
    with pytest.raises(PermissionError, match="workspace changed"):
        authorize(session(), worktree_digest=hashlib.sha256(b"changed").hexdigest())


def test_state_epoch_revocation_invalidates_session() -> None:
    with pytest.raises(PermissionError, match="state epoch"):
        authorize(session(), state_epoch=8)


def test_capabilities_are_explicit_and_fail_closed() -> None:
    with pytest.raises(PermissionError, match="capability"):
        authorize(session(), capability="file_write")
    with pytest.raises(ValueError, match="unknown capability"):
        session(capabilities=["preview_open", "shell_unbounded"])


def test_expired_or_not_yet_active_session_is_denied() -> None:
    with pytest.raises(PermissionError, match="expired or not active"):
        authorize(session(), now="2026-09-02T18:00:00Z")
    with pytest.raises(PermissionError, match="expired or not active"):
        authorize(session(), now="2026-09-02T12:59:59Z")


def test_tampering_and_secret_like_extension_are_rejected() -> None:
    row = copy.deepcopy(session())
    row["capabilities"] = ["file_read", "file_write", "preview_open"]
    with pytest.raises(ValueError, match="modified"):
        authorize(row)
    row = session()
    row["api_key"] = "must-not-persist"
    with pytest.raises(ValueError, match="schema"):
        authorize(row)


def test_ttl_is_bounded() -> None:
    with pytest.raises(ValueError, match="ttl out of bounds"):
        session(expires_at="2026-09-03T00:00:01Z")
