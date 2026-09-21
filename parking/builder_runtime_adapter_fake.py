"""Reversible reference/fake for Captain BuilderRuntimeAdapter.

Parking code only: no external runtime, subprocess, network, filesystem or paid API use.
The real Captain control-plane remains authoritative.
"""
from dataclasses import dataclass
from typing import Optional


class ScopeError(PermissionError):
    pass


@dataclass(frozen=True)
class BuilderScope:
    chat_id: str
    project_id: str
    repo_scope: str
    builder_session_id: str
    state_epoch: int

    def validate(self) -> None:
        vals = (self.chat_id, self.project_id, self.repo_scope, self.builder_session_id)
        if any(not isinstance(v, str) or not v.strip() for v in vals):
            raise ScopeError("invalid builder scope")
        if isinstance(self.state_epoch, bool) or not isinstance(self.state_epoch, int) or self.state_epoch < 0:
            raise ScopeError("invalid state epoch")


@dataclass
class Session:
    scope: BuilderScope
    checkpoint: int = 0
    preview_owner: Optional[BuilderScope] = None
    stopped: bool = False


class FakeBuilderRuntimeAdapter:
    """In-memory acceptance fake. Native session IDs never grant authority."""

    def __init__(self):
        self._sessions: dict[str, Session] = {}

    def create(self, scope: BuilderScope) -> str:
        scope.validate()
        sid = scope.builder_session_id
        existing = self._sessions.get(sid)
        if existing and existing.scope != scope:
            raise ScopeError("session id already owned by another scope")
        self._sessions[sid] = existing or Session(scope=scope)
        return sid

    def _owned(self, scope: BuilderScope) -> Session:
        scope.validate()
        s = self._sessions.get(scope.builder_session_id)
        if s is None or s.stopped or s.scope != scope:
            raise ScopeError("builder session scope mismatch")
        return s

    def inspect(self, scope: BuilderScope) -> dict:
        s = self._owned(scope)
        return {"checkpoint": s.checkpoint, "preview": s.preview_owner is not None}

    def checkpoint(self, scope: BuilderScope) -> int:
        s = self._owned(scope)
        s.checkpoint += 1
        return s.checkpoint

    def rollback(self, scope: BuilderScope, checkpoint: int) -> int:
        s = self._owned(scope)
        if isinstance(checkpoint, bool) or not isinstance(checkpoint, int) or checkpoint < 0 or checkpoint > s.checkpoint:
            raise ScopeError("checkpoint is not owned by current session history")
        s.checkpoint = checkpoint
        return checkpoint

    def preview(self, scope: BuilderScope) -> str:
        s = self._owned(scope)
        if s.preview_owner is not None and s.preview_owner != scope:
            raise ScopeError("preview owned by another scope")
        s.preview_owner = scope
        return f"captain-preview://{scope.builder_session_id}"

    def stop(self, scope: BuilderScope) -> None:
        s = self._owned(scope)
        s.preview_owner = None
        s.stopped = True
