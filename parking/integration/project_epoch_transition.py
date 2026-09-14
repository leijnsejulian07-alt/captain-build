from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from parking.integration.builder_output_handles import BuilderOutputHandleStore
from parking.integration.scope_contract import parse_scope


class EpochTransitionError(ValueError):
    pass


@dataclass(frozen=True)
class EpochTransitionResult:
    previous_epoch: int
    current_epoch: int
    revoked_builder_handles: int


class SupportsEpochCleanup(Protocol):
    def revoke_stale_epochs(self, *, chat_id: str, project_id: str, repo_scope: str, current_epoch: int) -> int: ...


def apply_project_epoch_transition(
    *,
    chat_id: str,
    project_id: str,
    repo_scope: str,
    previous_epoch: int,
    current_epoch: int,
    builder_outputs: SupportsEpochCleanup,
) -> EpochTransitionResult:
    """Apply security cleanup for one exact Captain Project State transition.

    This hook is intentionally narrow and side-effect bounded. It never advances Project
    State itself; the Captain control-plane owns that authority. It only performs cleanup
    after the caller supplies a verified monotonic epoch transition for one exact scope.
    """
    parse_scope({"chat_id": chat_id, "project_id": project_id, "repo_scope": repo_scope})
    for name, value in (("previous_epoch", previous_epoch), ("current_epoch", current_epoch)):
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise EpochTransitionError(f"invalid {name}")
    if current_epoch <= previous_epoch:
        raise EpochTransitionError("Project State epoch must advance monotonically")
    if builder_outputs is None or not hasattr(builder_outputs, "revoke_stale_epochs"):
        raise EpochTransitionError("missing builder output cleanup dependency")

    revoked = builder_outputs.revoke_stale_epochs(
        chat_id=chat_id,
        project_id=project_id,
        repo_scope=repo_scope,
        current_epoch=current_epoch,
    )
    if isinstance(revoked, bool) or not isinstance(revoked, int) or revoked < 0:
        raise EpochTransitionError("invalid builder cleanup result")
    return EpochTransitionResult(previous_epoch, current_epoch, revoked)
