"""Fail-closed artifact contract for Captain's builder subsystem."""
from __future__ import annotations
from dataclasses import dataclass, replace
from hashlib import sha256
import re

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,95}$")
_ALLOWED = {"source", "diff", "console", "preview", "test", "build"}
_TERMINAL = {"committed", "rolled_back", "rejected"}


def _valid_id(value: str) -> bool:
    return isinstance(value, str) and bool(_ID.fullmatch(value)) and ".." not in value


def _scope_hash(repo_scope: str) -> str:
    if not isinstance(repo_scope, str) or not repo_scope.strip():
        raise ValueError("repo_scope required")
    return sha256(repo_scope.strip().encode()).hexdigest()


@dataclass(frozen=True)
class BuilderArtifact:
    artifact_id: str
    chat_id: str
    project_id: str
    repo_scope_hash: str
    builder_session_id: str
    kind: str
    revision: int
    content_sha256: str
    state: str = "staged"


def create_artifact(*, artifact_id: str, chat_id: str, project_id: str,
                    repo_scope: str, builder_session_id: str, kind: str,
                    revision: int, content: bytes) -> BuilderArtifact:
    for value in (artifact_id, chat_id, project_id, builder_session_id):
        if not _valid_id(value):
            raise ValueError("invalid scoped id")
    if kind not in _ALLOWED:
        raise ValueError("unsupported artifact kind")
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
        raise ValueError("revision must be positive integer")
    if not isinstance(content, bytes) or len(content) > 2_000_000:
        raise ValueError("artifact content invalid or too large")
    return BuilderArtifact(artifact_id, chat_id, project_id, _scope_hash(repo_scope),
                           builder_session_id, kind, revision, sha256(content).hexdigest())


def can_access(artifact: BuilderArtifact, *, chat_id: str, project_id: str,
               repo_scope: str, builder_session_id: str) -> bool:
    try:
        return (artifact.chat_id == chat_id and artifact.project_id == project_id
                and artifact.repo_scope_hash == _scope_hash(repo_scope)
                and artifact.builder_session_id == builder_session_id)
    except (TypeError, ValueError):
        return False


def transition(artifact: BuilderArtifact, new_state: str) -> BuilderArtifact:
    allowed = {"staged": {"verified", "rejected"},
               "verified": {"committed", "rolled_back", "rejected"}}
    if artifact.state in _TERMINAL or new_state not in allowed.get(artifact.state, set()):
        raise ValueError("invalid artifact transition")
    return replace(artifact, state=new_state)


def next_revision(previous: BuilderArtifact, *, revision: int, content: bytes) -> BuilderArtifact:
    if previous.state in _TERMINAL:
        raise ValueError("terminal artifact cannot be revised")
    if isinstance(revision, bool) or not isinstance(revision, int) or revision <= previous.revision:
        raise ValueError("revision must increase")
    if not isinstance(content, bytes) or len(content) > 2_000_000:
        raise ValueError("artifact content invalid or too large")
    return replace(previous, revision=revision, content_sha256=sha256(content).hexdigest(), state="staged")
