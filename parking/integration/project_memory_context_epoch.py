from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from .scope_contract import ScopeKey, assert_same_scope, parse_scope

_ALLOWED_KINDS = {"project_memory", "project_context", "chat_context"}


@dataclass(frozen=True)
class ProjectStateEpoch:
    scope: ScopeKey
    state_epoch: int

    @classmethod
    def create(cls, scope: Mapping[str, object] | ScopeKey, state_epoch: int) -> "ProjectStateEpoch":
        parsed = parse_scope(scope)
        if isinstance(state_epoch, bool) or not isinstance(state_epoch, int) or state_epoch < 1:
            raise ValueError("invalid state_epoch")
        return cls(parsed, state_epoch)


@dataclass(frozen=True)
class MemoryContextRecord:
    kind: str
    scope: ScopeKey
    state_epoch: int
    record_id: str

    def validate(self) -> None:
        if self.kind not in _ALLOWED_KINDS:
            raise ValueError("invalid memory/context kind")
        parse_scope(self.scope)
        if isinstance(self.state_epoch, bool) or not isinstance(self.state_epoch, int) or self.state_epoch < 1:
            raise ValueError("invalid state_epoch")
        if not isinstance(self.record_id, str) or not self.record_id or len(self.record_id) > 160:
            raise ValueError("invalid record_id")

    def authorize(self, active: ProjectStateEpoch, *, requesting_chat_id: str | None = None) -> None:
        self.validate()
        assert_same_scope(active.scope, self.scope)
        if self.state_epoch != active.state_epoch:
            raise PermissionError("stale project memory/context epoch")
        if self.kind == "chat_context":
            if requesting_chat_id is None or requesting_chat_id != self.scope.chat_id:
                raise PermissionError("chat context is chat-bound")
        elif requesting_chat_id is not None and requesting_chat_id != active.scope.chat_id:
            # durable project memory/context may cross chats only through a scope explicitly
            # reconstructed for that chat by the Captain control-plane.
            raise PermissionError("requesting chat does not own active scope")


def authorize_normal_chat(*, project_id: str | None, repo_scope: str | None, state_epoch: int | None) -> None:
    """Non-project chat stays usable only when no partial project authority is present."""
    supplied = (project_id is not None, repo_scope is not None, state_epoch is not None)
    if any(supplied):
        raise PermissionError("partial project authority is not valid for normal chat")
