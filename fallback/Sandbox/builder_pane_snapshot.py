from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from openbuilder_execution_flow import OpenBuilderExecution
from sandbox_session_policy import assert_sandbox_access

PaneTab = Literal["code", "files", "preview", "console", "diffs", "rollback"]
_ALLOWED_TABS = {"code", "files", "preview", "console", "diffs", "rollback"}


@dataclass(frozen=True)
class BuilderPaneSnapshot:
    chat_id: str
    project_id: str
    repo_scope: str
    state_epoch: int
    sandbox_session_id: str
    phase: str
    active_tab: PaneTab
    preview_ref: str | None
    diff_ref: str | None
    console_ref: str | None
    rollback_ref: str | None
    can_promote: bool
    can_rollback: bool


def _safe_ref(name: str, value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    if not cleaned or "\n" in cleaned or "\r" in cleaned or "\x00" in cleaned:
        raise ValueError(f"invalid {name}")
    # References must be opaque identifiers/paths only; never raw output, diffs, logs, or secrets.
    if len(cleaned) > 512:
        raise ValueError(f"{name} too long")
    return cleaned


def project_builder_pane(
    execution: OpenBuilderExecution,
    *,
    chat_id: str,
    project_id: str,
    repo_scope: str,
    state_epoch: int,
    active_tab: PaneTab = "code",
    diff_ref: str | None = None,
    console_ref: str | None = None,
) -> BuilderPaneSnapshot:
    if active_tab not in _ALLOWED_TABS:
        raise ValueError("unsupported builder pane tab")

    assert_sandbox_access(
        execution.lease,
        chat_id=chat_id,
        project_id=project_id,
        repo_scope=repo_scope,
        state_epoch=state_epoch,
    )

    receipt = execution.receipt
    if receipt is not None and receipt.sandbox_session_id != execution.lease.session_id:
        raise PermissionError("receipt/sandbox session mismatch")

    rollback_ref = _safe_ref("rollback_ref", receipt.rollback_ref if receipt is not None else None)
    preview_ref = _safe_ref("preview_ref", execution.preview_ref)
    diff_ref = _safe_ref("diff_ref", diff_ref)
    console_ref = _safe_ref("console_ref", console_ref)

    can_promote = (
        execution.phase == "preview_ready"
        and receipt is not None
        and receipt.tests_status == "passed"
        and receipt.review_status == "passed"
        and receipt.promotable
        and preview_ref is not None
    )
    can_rollback = execution.phase not in {"promoted", "rolled_back"}

    return BuilderPaneSnapshot(
        chat_id=chat_id,
        project_id=project_id,
        repo_scope=repo_scope,
        state_epoch=state_epoch,
        sandbox_session_id=execution.lease.session_id,
        phase=execution.phase,
        active_tab=active_tab,
        preview_ref=preview_ref,
        diff_ref=diff_ref,
        console_ref=console_ref,
        rollback_ref=rollback_ref,
        can_promote=can_promote,
        can_rollback=can_rollback,
    )


def assert_builder_pane_access(
    snapshot: BuilderPaneSnapshot,
    *,
    chat_id: str,
    project_id: str,
    repo_scope: str,
    state_epoch: int,
) -> None:
    if (
        snapshot.chat_id != chat_id
        or snapshot.project_id != project_id
        or snapshot.repo_scope != repo_scope
        or snapshot.state_epoch != state_epoch
    ):
        raise PermissionError("builder pane scope/epoch mismatch")
