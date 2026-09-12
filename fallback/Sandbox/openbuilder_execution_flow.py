from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Literal

from sandbox_session_policy import SandboxLease, assert_sandbox_access
from builder_execution_receipt import (
    BuildExecutionReceipt,
    assert_receipt_access,
    require_promotion_ready,
)

BuildPhase = Literal[
    "leased",
    "building",
    "testing",
    "reviewing",
    "preview_ready",
    "promoted",
    "rolled_back",
]

_ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "leased": {"building", "rolled_back"},
    "building": {"testing", "rolled_back"},
    "testing": {"reviewing", "rolled_back"},
    "reviewing": {"preview_ready", "rolled_back"},
    "preview_ready": {"promoted", "rolled_back"},
    "promoted": set(),
    "rolled_back": set(),
}


@dataclass(frozen=True)
class OpenBuilderExecution:
    lease: SandboxLease
    phase: BuildPhase = "leased"
    receipt: BuildExecutionReceipt | None = None
    preview_ref: str | None = None


def _assert_authority(
    execution: OpenBuilderExecution,
    *,
    chat_id: str,
    project_id: str,
    repo_scope: str,
    state_epoch: int,
) -> None:
    assert_sandbox_access(
        execution.lease,
        chat_id=chat_id,
        project_id=project_id,
        repo_scope=repo_scope,
        state_epoch=state_epoch,
    )
    if execution.receipt is not None:
        assert_receipt_access(
            execution.receipt,
            chat_id=chat_id,
            project_id=project_id,
            repo_scope=repo_scope,
            state_epoch=state_epoch,
        )
        if execution.receipt.sandbox_session_id != execution.lease.session_id:
            raise PermissionError("build receipt belongs to a different sandbox session")


def _transition(execution: OpenBuilderExecution, target: BuildPhase) -> OpenBuilderExecution:
    if target not in _ALLOWED_TRANSITIONS[execution.phase]:
        raise PermissionError(f"invalid OpenBuilder transition: {execution.phase} -> {target}")
    return replace(execution, phase=target)


def begin_build(execution: OpenBuilderExecution, **authority) -> OpenBuilderExecution:
    _assert_authority(execution, **authority)
    return _transition(execution, "building")


def begin_tests(execution: OpenBuilderExecution, **authority) -> OpenBuilderExecution:
    _assert_authority(execution, **authority)
    return _transition(execution, "testing")


def begin_review(execution: OpenBuilderExecution, **authority) -> OpenBuilderExecution:
    _assert_authority(execution, **authority)
    return _transition(execution, "reviewing")


def attach_verified_receipt(
    execution: OpenBuilderExecution,
    receipt: BuildExecutionReceipt,
    **authority,
) -> OpenBuilderExecution:
    _assert_authority(execution, **authority)
    if execution.phase != "reviewing":
        raise PermissionError("receipt may only be attached after build/test review")
    candidate = replace(execution, receipt=receipt)
    _assert_authority(candidate, **authority)
    require_promotion_ready(receipt)
    return candidate


def mark_preview_ready(
    execution: OpenBuilderExecution,
    *,
    preview_ref: str,
    **authority,
) -> OpenBuilderExecution:
    _assert_authority(execution, **authority)
    if execution.receipt is None:
        raise PermissionError("preview requires a verified build receipt")
    require_promotion_ready(execution.receipt)
    value = (preview_ref or "").strip()
    if not value or "\n" in value or "\r" in value or "\x00" in value:
        raise ValueError("invalid preview_ref")
    return replace(_transition(execution, "preview_ready"), preview_ref=value)


def promote(execution: OpenBuilderExecution, **authority) -> OpenBuilderExecution:
    _assert_authority(execution, **authority)
    if execution.receipt is None or execution.preview_ref is None:
        raise PermissionError("promotion requires verified receipt and preview")
    require_promotion_ready(execution.receipt)
    return _transition(execution, "promoted")


def rollback(execution: OpenBuilderExecution, **authority) -> OpenBuilderExecution:
    _assert_authority(execution, **authority)
    if execution.phase in {"promoted", "rolled_back"}:
        raise PermissionError("terminal OpenBuilder execution cannot be rolled back again")
    return _transition(execution, "rolled_back")
