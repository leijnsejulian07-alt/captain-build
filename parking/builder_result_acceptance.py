"""Fail-closed acceptance gate for asynchronous Captain builder results.

Parking implementation: integrate behind Captain's existing control-plane only after
reconciling with the live workspace. No secrets or payload bodies are logged here.
"""
from dataclasses import dataclass

@dataclass(frozen=True)
class BuilderOwner:
    chat_id: str
    project_id: str
    repo_scope: str
    epoch: int
    builder_session_id: str

def accept_builder_result(expected: BuilderOwner, actual: BuilderOwner) -> bool:
    """Return True only for an exact, well-formed owner match."""
    for owner in (expected, actual):
        if not owner.chat_id or not owner.builder_session_id:
            return False
        if owner.epoch < 0:
            return False
        # project/repo may be empty only together for normal non-project chat.
        if bool(owner.project_id) != bool(owner.repo_scope):
            return False
    return expected == actual

def rejection_reason(expected: BuilderOwner, actual: BuilderOwner) -> str:
    """Safe reason code only; never include IDs, paths, payloads or credentials."""
    if accept_builder_result(expected, actual):
        return "accepted"
    if not actual.chat_id or not actual.builder_session_id or actual.epoch < 0:
        return "invalid_owner"
    if bool(actual.project_id) != bool(actual.repo_scope):
        return "invalid_scope"
    if expected.epoch != actual.epoch:
        return "stale_epoch"
    if expected.builder_session_id != actual.builder_session_id:
        return "stale_builder_session"
    return "owner_mismatch"
