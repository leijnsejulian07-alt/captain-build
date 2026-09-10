"""Epoch-bound OpenBuilder action receipts for Captain.

Builder subsystems may execute plan/build/test/review/debug/preview operations, but
Captain owns the authorization envelope and receipt ledger. A receipt is only
visible to the exact chat/project/repository/Project-State epoch that authorized
its action. This prevents delayed or replayed builder results from crossing an
epoch wall after a project switch or state transition.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Mapping, Optional

from .project_authority import AuthorityError, ProjectAuthority, require_current_epoch


FINAL_ACTION_STATUSES = frozenset({"succeeded", "failed", "cancelled", "rolled_back"})
ACTION_STATUSES = frozenset({"queued", "running", *FINAL_ACTION_STATUSES})


@dataclass(frozen=True)
class BuilderActionReceipt:
    action_id: str
    session_id: str
    action_type: str
    status: str
    authority: ProjectAuthority
    payload: Mapping[str, object]

    def validate(self) -> "BuilderActionReceipt":
        for value, label in (
            (self.action_id, "action_id"),
            (self.session_id, "session_id"),
            (self.action_type, "action_type"),
        ):
            if not isinstance(value, str) or not value.strip():
                raise AuthorityError(f"builder receipt requires a non-empty {label}")
        if self.status not in ACTION_STATUSES:
            raise AuthorityError("unknown builder action status must fail closed")
        self.authority.validate()
        if self.authority.is_normal_chat:
            raise AuthorityError("builder action receipts require complete project authority")
        return self


class EpochBoundBuilderActionLedger:
    """Captain-owned receipt ledger for builder actions and delayed results."""

    def __init__(self) -> None:
        self._receipts: Dict[str, BuilderActionReceipt] = {}

    def record(
        self,
        receipt: BuilderActionReceipt,
        *,
        actor: ProjectAuthority,
        current_epoch: int,
    ) -> None:
        self._validate_actor(actor, current_epoch=current_epoch)
        receipt.validate()
        actor.require_same_owner(receipt.authority)

        existing = self._receipts.get(receipt.action_id)
        if existing is not None:
            if not existing.authority.same_owner(actor):
                raise AuthorityError("builder action_id collision across authority wall")
            if existing.session_id != receipt.session_id or existing.action_type != receipt.action_type:
                raise AuthorityError("builder action identity cannot change after creation")
            if existing.status in FINAL_ACTION_STATUSES and receipt.status != existing.status:
                raise AuthorityError("final builder action receipt cannot be reopened or rewritten")

        self._receipts[receipt.action_id] = receipt

    def get(
        self,
        action_id: str,
        *,
        request: ProjectAuthority,
        current_epoch: int,
    ) -> Optional[BuilderActionReceipt]:
        self._validate_actor(request, current_epoch=current_epoch)
        receipt = self._receipts.get(action_id)
        if receipt is None:
            return None
        receipt.validate()
        if not receipt.authority.same_owner(request):
            return None
        return receipt

    def list_readable(
        self,
        *,
        request: ProjectAuthority,
        current_epoch: int,
        session_id: Optional[str] = None,
    ) -> List[BuilderActionReceipt]:
        self._validate_actor(request, current_epoch=current_epoch)
        if session_id is not None and (not isinstance(session_id, str) or not session_id.strip()):
            raise AuthorityError("session_id filter must be non-empty when provided")
        return [
            receipt
            for receipt in self._receipts.values()
            if receipt.authority.same_owner(request)
            and (session_id is None or receipt.session_id == session_id)
        ]

    def revoke_epoch(
        self,
        *,
        authority: ProjectAuthority,
        current_epoch: int,
    ) -> int:
        """Clean old receipts after a Project State transition.

        Current-epoch validation remains the security boundary; cleanup only
        removes receipts for older epochs of the same chat/project/repository.
        """
        self._validate_actor(authority, current_epoch=current_epoch)
        doomed = [
            action_id
            for action_id, receipt in self._receipts.items()
            if (
                receipt.authority.chat_id == authority.chat_id
                and receipt.authority.project_id == authority.project_id
                and receipt.authority.repo_scope == authority.repo_scope
                and receipt.authority.state_epoch != authority.state_epoch
            )
        ]
        for action_id in doomed:
            del self._receipts[action_id]
        return len(doomed)

    @staticmethod
    def _validate_actor(actor: ProjectAuthority, *, current_epoch: int) -> None:
        actor.validate()
        if actor.is_normal_chat:
            raise AuthorityError("normal chat cannot access builder action receipts")
        require_current_epoch(actor, current_epoch=current_epoch)
