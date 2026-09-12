from __future__ import annotations

from pathlib import Path
from typing import Mapping

from parking.integration.builder_backend_dispatch import validate_builder_backend_dispatch
from parking.integration.connector_dispatch_ledger import SQLiteDispatchLedger


class BuilderDispatchReplayError(PermissionError):
    pass


def consume_builder_dispatch_once(
    dispatch: Mapping[str, object],
    session: Mapping[str, object],
    *,
    ledger_path: str | Path,
    request_id: str,
    chat_id: str,
    project_id: str,
    repo_scope: str,
    session_id: str,
    repo_head: str,
    worktree_digest: str,
    state_epoch: int,
    capability: str,
    settings_state_digest: str,
    installed: bool,
    enabled: bool,
    ready: bool,
    now: str,
) -> dict[str, object]:
    """Validate current Captain authority and atomically consume a builder dispatch once.

    The dispatch binding digest is used as the opaque single-use ticket id. Validation
    happens immediately before the durable consume, so current Project State epoch,
    builder session/worktree, capability and canonical Settings readiness still revoke
    stale work. The ledger stores only ticket/request/scope digests and a timestamp.
    """
    validated = validate_builder_backend_dispatch(
        dispatch,
        session,
        chat_id=chat_id,
        project_id=project_id,
        repo_scope=repo_scope,
        session_id=session_id,
        repo_head=repo_head,
        worktree_digest=worktree_digest,
        state_epoch=state_epoch,
        capability=capability,
        settings_state_digest=settings_state_digest,
        installed=installed,
        enabled=enabled,
        ready=ready,
        now=now,
    )
    ticket_id = validated.get("binding_digest")
    if not isinstance(ticket_id, str):
        raise ValueError("builder dispatch missing binding digest")

    ledger = SQLiteDispatchLedger(ledger_path)
    if not ledger.consume_once(
        ticket_id=ticket_id,
        chat_id=chat_id,
        project_id=project_id,
        repo_scope=repo_scope,
        request_id=request_id,
        consumed_at=now,
    ):
        raise BuilderDispatchReplayError("builder dispatch already consumed")
    return validated
