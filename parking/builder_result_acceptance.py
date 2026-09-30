"""Fail-closed acceptance gate for asynchronous Captain builder results.

Parking implementation: integrate behind Captain's existing control-plane only after
reconciling with the live workspace. No secrets or payload bodies are logged here.
"""
from dataclasses import dataclass
from typing import Any

@dataclass(frozen=True)
class BuilderOwner:
    chat_id: str
    project_id: str
    repo_scope: str
    epoch: int
    builder_session_id: str

def _valid_text(value: Any, *, allow_empty: bool = False) -> bool:
    if not isinstance(value, str):
        return False
    if allow_empty and value == "":
        return True
    return bool(value.strip())

def _valid_owner(owner: Any) -> bool:
    if not isinstance(owner, BuilderOwner):
        return False
    if not _valid_text(owner.chat_id) or not _valid_text(owner.builder_session_id):
        return False
    # bool is an int subclass; epochs must be actual non-negative integers.
    if isinstance(owner.epoch, bool) or not isinstance(owner.epoch, int) or owner.epoch < 0:
        return False
    if not isinstance(owner.project_id, str) or not isinstance(owner.repo_scope, str):
        return False
    project = owner.project_id.strip()
    repo = owner.repo_scope.strip()
    # Project/repo may be empty only together for normal non-project chat.
    if bool(project) != bool(repo):
        return False
    # Whitespace-only scope is never a valid project scope.
    if owner.project_id and not project:
        return False
    if owner.repo_scope and not repo:
        return False
    return True

def accept_builder_result(expected: BuilderOwner, actual: BuilderOwner) -> bool:
    """Return True only for an exact, well-formed owner match."""
    if not _valid_owner(expected) or not _valid_owner(actual):
        return False
    return expected == actual

def rejection_reason(expected: BuilderOwner, actual: BuilderOwner) -> str:
    """Safe reason code only; never include IDs, paths, payloads or credentials."""
    if accept_builder_result(expected, actual):
        return "accepted"
    if not _valid_owner(expected):
        return "invalid_expected_owner"
    if not _valid_owner(actual):
        return "invalid_owner"
    if expected.epoch != actual.epoch:
        return "stale_epoch"
    if expected.builder_session_id != actual.builder_session_id:
        return "stale_builder_session"
    return "owner_mismatch"
