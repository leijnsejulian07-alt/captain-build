"""Captain-owned causal state machine for OpenBuilder sessions.

Ownership/epoch walls answer *who* may act.  This module additionally answers
*when* a builder action/resource is valid inside a live session, preventing an
adapter from skipping plan/build/test/review gates and publishing a preview or
rollback artifact out of causal order.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional, Set, Tuple

from .builder_action_receipts import BuilderActionReceipt
from .project_authority import AuthorityError, ProjectAuthority


BUILDER_PHASES = frozenset({"plan", "build", "test", "review", "debug", "preview", "rollback"})
_PHASE_RESOURCE_REQUIREMENTS = {
    "diff": "build",
    "preview": "preview",
    "rollback": "rollback",
}

SessionPhaseKey = Tuple[str, str, str, int, str]


@dataclass
class _SessionPhaseState:
    completed: Set[str] = field(default_factory=set)
    attempted: Set[str] = field(default_factory=set)
    failed_phase: Optional[str] = None
    actions: Dict[str, str] = field(default_factory=dict)


class BuilderPhaseStateMachine:
    """Fail-closed causal ordering for one Captain-owned builder lifecycle."""

    def __init__(self) -> None:
        self._sessions: Dict[SessionPhaseKey, _SessionPhaseState] = {}

    @staticmethod
    def _key(authority: ProjectAuthority, session_id: str) -> SessionPhaseKey:
        authority.validate()
        if authority.is_normal_chat:
            raise AuthorityError("builder phases require project authority")
        if not isinstance(session_id, str) or not session_id.strip():
            raise AuthorityError("builder phases require a non-empty session_id")
        assert authority.chat_id is not None
        assert authority.project_id is not None
        assert authority.repo_scope is not None
        assert authority.state_epoch is not None
        return (
            authority.chat_id,
            authority.project_id,
            authority.repo_scope,
            authority.state_epoch,
            session_id,
        )

    def open_session(self, *, authority: ProjectAuthority, session_id: str) -> None:
        key = self._key(authority, session_id)
        if key in self._sessions:
            raise AuthorityError("builder phase session is already open")
        self._sessions[key] = _SessionPhaseState()

    def _state(self, *, authority: ProjectAuthority, session_id: str) -> _SessionPhaseState:
        key = self._key(authority, session_id)
        state = self._sessions.get(key)
        if state is None:
            raise AuthorityError("builder phase state requires a live session")
        return state

    @staticmethod
    def _require_phase_prerequisite(state: _SessionPhaseState, phase: str) -> None:
        completed = state.completed
        if phase == "plan":
            if "build" in state.attempted:
                raise AuthorityError("plan cannot restart after build has begun")
            return
        if phase == "build":
            if "plan" not in completed:
                raise AuthorityError("build requires a succeeded plan")
            return
        if phase == "test":
            if "build" not in completed:
                raise AuthorityError("test requires a succeeded build")
            return
        if phase == "review":
            if "test" not in completed:
                raise AuthorityError("review requires succeeded tests")
            return
        if phase == "debug":
            if state.failed_phase not in {"build", "test", "review"}:
                raise AuthorityError("debug requires a failed build/test/review phase")
            return
        if phase == "preview":
            if "review" not in completed:
                raise AuthorityError("preview requires a succeeded review")
            return
        if phase == "rollback":
            if "build" not in completed:
                raise AuthorityError("rollback requires a succeeded build")
            return
        raise AuthorityError("unknown builder phase must fail closed")

    def validate_receipt(self, receipt: BuilderActionReceipt) -> None:
        receipt.validate()
        if receipt.action_type not in BUILDER_PHASES:
            raise AuthorityError("builder action_type is not a recognized lifecycle phase")
        state = self._state(authority=receipt.authority, session_id=receipt.session_id)
        prior_phase = state.actions.get(receipt.action_id)
        if prior_phase is not None and prior_phase != receipt.action_type:
            raise AuthorityError("builder action phase cannot change after creation")
        self._require_phase_prerequisite(state, receipt.action_type)

    def apply_receipt(self, receipt: BuilderActionReceipt) -> None:
        """Apply a receipt after the canonical lifecycle ledger accepted it."""
        self.validate_receipt(receipt)
        state = self._state(authority=receipt.authority, session_id=receipt.session_id)
        phase = receipt.action_type
        state.actions.setdefault(receipt.action_id, phase)
        state.attempted.add(phase)

        if receipt.status == "failed":
            if phase in {"build", "test", "review"}:
                state.failed_phase = phase
            return
        if receipt.status != "succeeded":
            return

        state.completed.add(phase)
        if phase == "plan":
            return
        if phase == "build":
            state.completed.difference_update({"test", "review", "debug", "preview", "rollback"})
            state.failed_phase = None
        elif phase == "test":
            state.completed.difference_update({"review", "preview"})
            if state.failed_phase == "test":
                state.failed_phase = None
        elif phase == "review":
            state.completed.discard("preview")
            if state.failed_phase == "review":
                state.failed_phase = None
        elif phase == "debug":
            # Code changed during debugging; force the normal verification gates again.
            state.completed.difference_update({"test", "review", "preview"})
            state.failed_phase = None
        elif phase == "rollback":
            # The previous build is no longer the live candidate after rollback.
            state.completed.difference_update({"build", "test", "review", "debug", "preview"})
            state.failed_phase = None

    def require_resource(
        self,
        *,
        authority: ProjectAuthority,
        session_id: str,
        resource_type: str,
    ) -> None:
        state = self._state(authority=authority, session_id=session_id)
        required = _PHASE_RESOURCE_REQUIREMENTS.get(resource_type)
        if required is not None and required not in state.completed:
            raise AuthorityError(
                f"builder resource {resource_type!r} requires succeeded {required!r} phase"
            )

    def revoke_epoch(self, *, authority: ProjectAuthority) -> int:
        """Drop old phase state for this chat/project/repository owner."""
        authority.validate()
        if authority.is_normal_chat:
            raise AuthorityError("normal chat cannot revoke builder phase state")
        doomed = [
            key
            for key in self._sessions
            if key[0] == authority.chat_id
            and key[1] == authority.project_id
            and key[2] == authority.repo_scope
            and key[3] != authority.state_epoch
        ]
        for key in doomed:
            del self._sessions[key]
        return len(doomed)
