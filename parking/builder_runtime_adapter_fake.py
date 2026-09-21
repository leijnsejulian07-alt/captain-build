"""Reversible reference/fake for Captain BuilderRuntimeAdapter.

Parking code only: no external runtime, subprocess, network, filesystem or paid API use.
The real Captain control-plane remains authoritative.
"""
from dataclasses import dataclass, field
from typing import Optional


class ScopeError(PermissionError):
    pass


MAX_FILE_BYTES = 2_000_000
MAX_SESSION_BYTES = 16_000_000
MAX_SESSION_FILES = 512
MAX_LOG_EVENTS = 2_000
MAX_CHECKPOINTS = 64


def _safe_relpath(path: str) -> str:
    if not isinstance(path, str) or not path or len(path) > 1024 or "\x00" in path or "\\" in path:
        raise ScopeError("invalid repository-relative path")
    parts = path.split("/")
    if path.startswith("/") or any(p in ("", ".", "..") for p in parts) or (parts and ":" in parts[0]):
        raise ScopeError("invalid repository-relative path")
    return path


def _utf8_size(value: str) -> int:
    return len(value.encode("utf-8"))


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
    files: dict[str, str] = field(default_factory=dict)
    logs: list[str] = field(default_factory=list)
    snapshots: dict[int, tuple[dict[str, str], int]] = field(default_factory=lambda: {0: ({}, 0)})


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
        if existing and existing.stopped:
            raise ScopeError("stopped session id cannot be resurrected")
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
        return {"checkpoint": s.checkpoint, "preview": s.preview_owner is not None,
                "file_count": len(s.files), "log_count": len(s.logs),
                "bytes_used": sum(_utf8_size(v) for v in s.files.values())}

    def list_files(self, scope: BuilderScope, prefix: str = "", limit: int = 1000) -> tuple[str, ...]:
        s = self._owned(scope)
        if prefix:
            prefix = _safe_relpath(prefix)
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1 or limit > 1000:
            raise ScopeError("invalid file listing limit")
        return tuple(p for p in sorted(s.files) if not prefix or p == prefix or p.startswith(prefix + "/"))[:limit]

    def write_file(self, scope: BuilderScope, path: str, content: str) -> None:
        s = self._owned(scope); path = _safe_relpath(path)
        if not isinstance(content, str) or _utf8_size(content) > MAX_FILE_BYTES:
            raise ScopeError("invalid file content")
        if path not in s.files and len(s.files) >= MAX_SESSION_FILES:
            raise ScopeError("builder session file quota exceeded")
        old_size = _utf8_size(s.files.get(path, ""))
        used = sum(_utf8_size(v) for v in s.files.values())
        if used - old_size + _utf8_size(content) > MAX_SESSION_BYTES:
            raise ScopeError("builder session byte quota exceeded")
        s.files[path] = content

    def read_file(self, scope: BuilderScope, path: str) -> str:
        s = self._owned(scope); path = _safe_relpath(path)
        if path not in s.files:
            raise ScopeError("file is not owned by current builder session")
        return s.files[path]

    def delete_file(self, scope: BuilderScope, path: str) -> None:
        s = self._owned(scope); path = _safe_relpath(path)
        if path not in s.files:
            raise ScopeError("file is not owned by current builder session")
        del s.files[path]

    def diff(self, scope: BuilderScope) -> dict[str, str]:
        s = self._owned(scope)
        base, _ = s.snapshots.get(s.checkpoint, ({}, 0))
        keys = set(base) | set(s.files)
        return {p: s.files.get(p, "<deleted>") for p in sorted(keys) if base.get(p) != s.files.get(p)}

    def run(self, scope: BuilderScope, command: str) -> str:
        s = self._owned(scope)
        if not isinstance(command, str) or not command.strip() or len(command) > 4096 or "\x00" in command:
            raise ScopeError("invalid command")
        if len(s.logs) >= MAX_LOG_EVENTS:
            raise ScopeError("builder session log quota exceeded")
        # Acceptance fake only: never execute and never persist raw command text.
        event = "fake-run:accepted"
        s.logs.append(event)
        return event

    def logs(self, scope: BuilderScope) -> tuple[str, ...]:
        return tuple(self._owned(scope).logs)

    def checkpoint(self, scope: BuilderScope) -> int:
        s = self._owned(scope)
        if len(s.snapshots) >= MAX_CHECKPOINTS:
            raise ScopeError("builder session checkpoint quota exceeded")
        s.checkpoint += 1
        s.snapshots[s.checkpoint] = (dict(s.files), len(s.logs))
        return s.checkpoint

    def rollback(self, scope: BuilderScope, checkpoint: int) -> int:
        s = self._owned(scope)
        if isinstance(checkpoint, bool) or not isinstance(checkpoint, int) or checkpoint < 0 or checkpoint not in s.snapshots:
            raise ScopeError("checkpoint is not owned by current session history")
        files, log_len = s.snapshots[checkpoint]
        s.files = dict(files)
        s.logs = s.logs[:log_len]
        s.checkpoint = checkpoint
        for cp in tuple(s.snapshots):
            if cp > checkpoint:
                del s.snapshots[cp]
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
