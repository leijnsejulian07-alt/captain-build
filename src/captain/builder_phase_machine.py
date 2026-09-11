"""Captain-owned causal state machine for OpenBuilder sessions.

Ownership/epoch walls answer *who* may act. This module additionally answers
*when* a builder action/resource is valid inside a live session, preventing an
adapter from skipping plan/build/test/review gates and publishing a preview or
rollback artifact out of causal order.

Phase state can be exported/restored as a strict secret-free checkpoint. This
lets Captain recover durable builder jobs after a desktop restart without
silently forgetting which verification gates actually succeeded.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Mapping, Optional, Set, Tuple

from .builder_action_receipts import BuilderActionReceipt
from .project_authority import AuthorityError, ProjectAuthority, require_current_epoch


BUILDER_PHASES = frozenset({"plan", "build", "test", "review", "debug", "preview", "rollback"})
_PHASE_RESOURCE_REQUIREMENTS = {
    "diff": "build",
    "preview": "preview",
    "rollback": "rollback",
}
_FAILED_PHASES = frozenset({"build", "test", "review"})

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

    @staticmethod
    def _validate_actor(authority: ProjectAuthority, *, current_epoch: int) -> None:
        authority.validate()
        if authority.is_normal_chat:
            raise AuthorityError("normal chat cannot access builder phase state")
        require_current_epoch(authority, current_epoch=current_epoch)

    @staticmethod
    def _validate_restored_state(state: _SessionPhaseState) -> None:
        if not state.completed.issubset(BUILDER_PHASES):
            raise AuthorityError("restored builder phase state has unknown completed phase")
        if not state.attempted.issubset(BUILDER_PHASES):
            raise AuthorityError("restored builder phase state has unknown attempted phase")
        if not state.completed.issubset(state.attempted):
            raise AuthorityError("completed builder phases must have been attempted")

        # A persisted checkpoint is untrusted input. Re-prove the same causal
        # gates the live state machine enforces instead of accepting a caller's
        # claim that a later phase succeeded.
        if "build" in state.completed and "plan" not in state.completed:
            raise AuthorityError("restored build success requires succeeded plan")
        if "test" in state.completed and "build" not in state.completed:
            raise AuthorityError("restored test success requires succeeded build")
        if "review" in state.completed and "test" not in state.completed:
            raise AuthorityError("restored review success requires succeeded tests")
        if "preview" in state.completed and "review" not in state.completed:
            raise AuthorityError("restored preview success requires succeeded review")
        if "rollback" in state.completed:
            if "build" not in state.attempted:
                raise AuthorityError("restored rollback requires a previously attempted build")
            if state.completed.intersection({"build", "test", "review", "debug", "preview"}):
                raise AuthorityError("restored rollback state contains invalidated build phases")
        if "debug" in state.completed and not state.attempted.intersection(_FAILED_PHASES):
            raise AuthorityError("restored debug requires a prior failed-phase attempt")

        if state.failed_phase is not None:
            if state.failed_phase not in _FAILED_PHASES:
                raise AuthorityError("restored builder phase state has invalid failed phase")
            if state.failed_phase not in state.attempted:
                raise AuthorityError("failed builder phase must have been attempted")
        for action_id, phase in state.actions.items():
            if not isinstance(action_id, str) or not action_id.strip():
                raise AuthorityError("restored builder action id is invalid")
            if phase not in BUILDER_PHASES:
                raise AuthorityError("restored builder action has unknown phase")
            if phase not in state.attempted:
                raise AuthorityError("restored builder action phase must have been attempted")

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
            if state.failed_phase not in _FAILED_PHASES:
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
            if phase in _FAILED_PHASES:
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
            state.completed.difference_update({"test", "review", "preview"})
            state.failed_phase = None
        elif phase == "rollback":
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

    def export_state(
        self,
        *,
        authority: ProjectAuthority,
        session_id: str,
        current_epoch: int,
    ) -> Mapping[str, object]:
        """Return canonical secret-free causal state for durable restart recovery."""
        self._validate_actor(authority, current_epoch=current_epoch)
        state = self._state(authority=authority, session_id=session_id)
        self._validate_restored_state(state)
        return {
            "session_id": session_id,
            "chat_id": authority.chat_id,
            "project_id": authority.project_id,
            "repo_scope": authority.repo_scope,
            "state_epoch": authority.state_epoch,
            "completed": sorted(state.completed),
            "attempted": sorted(state.attempted),
            "failed_phase": state.failed_phase,
            "actions": {key: state.actions[key] for key in sorted(state.actions)},
        }

    def restore_state(
        self,
        record: Mapping[str, object],
        *,
        authority: ProjectAuthority,
        current_epoch: int,
    ) -> None:
        """Restore one exact owner+epoch session phase checkpoint, fail closed."""
        self._validate_actor(authority, current_epoch=current_epoch)
        if type(record) is not dict:
            raise AuthorityError("builder phase restore record must be a canonical dict")
        expected = {
            "session_id", "chat_id", "project_id", "repo_scope", "state_epoch",
            "completed", "attempted", "failed_phase", "actions",
        }
        if set(record) != expected:
            raise AuthorityError("builder phase restore record has unexpected fields")

        restored_authority = ProjectAuthority(
            chat_id=record["chat_id"],
            project_id=record["project_id"],
            repo_scope=record["repo_scope"],
            state_epoch=record["state_epoch"],
        )
        authority.require_same_owner(restored_authority)
        require_current_epoch(restored_authority, current_epoch=current_epoch)

        session_id = record["session_id"]
        if not isinstance(session_id, str) or not session_id.strip():
            raise AuthorityError("restored builder session_id is invalid")
        if type(record["completed"]) is not list or type(record["attempted"]) is not list:
            raise AuthorityError("restored builder phase sets must be canonical lists")
        if not all(isinstance(item, str) for item in record["completed"]):
            raise AuthorityError("restored completed phases must be strings")
        if not all(isinstance(item, str) for item in record["attempted"]):
            raise AuthorityError("restored attempted phases must be strings")
        if len(set(record["completed"])) != len(record["completed"]):
            raise AuthorityError("restored completed phases contain duplicates")
        if len(set(record["attempted"])) != len(record["attempted"]):
            raise AuthorityError("restored attempted phases contain duplicates")
        failed_phase = record["failed_phase"]
        if failed_phase is not None and not isinstance(failed_phase, str):
            raise AuthorityError("restored failed phase must be a string or null")
        actions = record["actions"]
        if type(actions) is not dict:
            raise AuthorityError("restored builder actions must be a canonical dict")
        if not all(isinstance(key, str) and isinstance(value, str) for key, value in actions.items()):
            raise AuthorityError("restored builder action entries must be strings")

        state = _SessionPhaseState(
            completed=set(record["completed"]),
            attempted=set(record["attempted"]),
            failed_phase=failed_phase,
            actions=dict(actions),
        )
        self._validate_restored_state(state)
        key = self._key(authority, session_id)
        if key in self._sessions:
            raise AuthorityError("builder phase restore cannot overwrite a live session")
        self._sessions[key] = state

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
