"""Epoch-bound OpenBuilder action receipts for Captain.

Builder subsystems may execute plan/build/test/review/debug/preview operations, but
Captain owns the authorization envelope and receipt ledger. A receipt is only
visible to the exact chat/project/repository/Project-State epoch that authorized
its action. This prevents delayed or replayed builder results from crossing an
epoch wall after a project switch or state transition.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from types import MappingProxyType
from typing import Dict, List, Mapping, Optional, Tuple

from .project_authority import AuthorityError, ProjectAuthority, require_current_epoch


FINAL_ACTION_STATUSES = frozenset({"succeeded", "failed", "cancelled", "rolled_back"})
ACTION_STATUSES = frozenset({"queued", "running", *FINAL_ACTION_STATUSES})
_ALLOWED_TRANSITIONS = {
    "queued": frozenset({"queued", "running", "succeeded", "failed", "cancelled"}),
    "running": frozenset({"running", "succeeded", "failed", "cancelled", "rolled_back"}),
    "succeeded": frozenset({"succeeded"}),
    "failed": frozenset({"failed"}),
    "cancelled": frozenset({"cancelled"}),
    "rolled_back": frozenset({"rolled_back"}),
}

BuilderActionKey = Tuple[str, str, str, int, str]


def _freeze_payload_value(value: object, *, path: str = "$") -> object:
    """Snapshot receipt payloads into immutable JSON-like builtin values."""
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise AuthorityError(f"builder receipt payload contains non-finite float at {path}")
        return value
    if type(value) is dict:
        frozen: Dict[str, object] = {}
        for key, nested in value.items():
            if not isinstance(key, str) or not key:
                raise AuthorityError(
                    f"builder receipt payload keys must be non-empty strings at {path}"
                )
            frozen[key] = _freeze_payload_value(nested, path=f"{path}.{key}")
        return MappingProxyType(frozen)
    if type(value) in {list, tuple}:
        return tuple(
            _freeze_payload_value(nested, path=f"{path}[{index}]")
            for index, nested in enumerate(value)
        )
    raise AuthorityError(
        "builder receipt payload contains unsupported mutable/custom value "
        f"at {path}: {type(value).__name__}"
    )


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
        if type(self.payload) is not dict and not isinstance(self.payload, MappingProxyType):
            raise AuthorityError("builder receipt payload must be a canonical mapping")
        return self


def _snapshot_receipt(receipt: BuilderActionReceipt) -> BuilderActionReceipt:
    receipt.validate()
    payload = _freeze_payload_value(dict(receipt.payload))
    assert isinstance(payload, Mapping)
    return BuilderActionReceipt(
        action_id=receipt.action_id,
        session_id=receipt.session_id,
        action_type=receipt.action_type,
        status=receipt.status,
        authority=receipt.authority,
        payload=payload,
    )


class EpochBoundBuilderActionLedger:
    """Captain-owned receipt ledger for builder actions and delayed results."""

    def __init__(self) -> None:
        self._receipts: Dict[BuilderActionKey, BuilderActionReceipt] = {}

    @staticmethod
    def _storage_key(authority: ProjectAuthority, action_id: str) -> BuilderActionKey:
        authority.validate()
        if authority.is_normal_chat:
            raise AuthorityError("normal chat cannot own builder action receipts")
        if not isinstance(action_id, str) or not action_id.strip():
            raise AuthorityError("builder receipt requires a non-empty action_id")
        assert authority.chat_id is not None
        assert authority.project_id is not None
        assert authority.repo_scope is not None
        assert authority.state_epoch is not None
        return (
            authority.chat_id,
            authority.project_id,
            authority.repo_scope,
            authority.state_epoch,
            action_id,
        )

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

        key = self._storage_key(actor, receipt.action_id)
        existing = self._receipts.get(key)
        if existing is not None:
            if existing.session_id != receipt.session_id or existing.action_type != receipt.action_type:
                raise AuthorityError("builder action identity cannot change after creation")
            if receipt.status not in _ALLOWED_TRANSITIONS[existing.status]:
                raise AuthorityError(
                    f"invalid builder action status transition: {existing.status} -> {receipt.status}"
                )

        self._receipts[key] = _snapshot_receipt(receipt)

    def get(
        self,
        action_id: str,
        *,
        request: ProjectAuthority,
        current_epoch: int,
    ) -> Optional[BuilderActionReceipt]:
        self._validate_actor(request, current_epoch=current_epoch)
        receipt = self._receipts.get(self._storage_key(request, action_id))
        if receipt is None:
            return None
        receipt.validate()
        if not receipt.authority.same_owner(request):
            raise AuthorityError("builder action storage key/authority mismatch")
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
            key
            for key, receipt in self._receipts.items()
            if (
                receipt.authority.chat_id == authority.chat_id
                and receipt.authority.project_id == authority.project_id
                and receipt.authority.repo_scope == authority.repo_scope
                and receipt.authority.state_epoch != authority.state_epoch
            )
        ]
        for key in doomed:
            del self._receipts[key]
        return len(doomed)

    @staticmethod
    def _validate_actor(actor: ProjectAuthority, *, current_epoch: int) -> None:
        actor.validate()
        if actor.is_normal_chat:
            raise AuthorityError("normal chat cannot access builder action receipts")
        require_current_epoch(actor, current_epoch=current_epoch)
