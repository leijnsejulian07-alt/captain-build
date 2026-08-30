"""Fail-closed preview session contract for Captain/OpenBuilder parking work."""
from dataclasses import dataclass
from hashlib import sha256
import re

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_ALLOWED_STATUS = {"starting", "ready", "failed", "stopped"}


def _stable_id(value: str, label: str) -> str:
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise ValueError(f"invalid {label}")
    return value


def _scope_hash(repo_scope: str) -> str:
    if not isinstance(repo_scope, str) or not repo_scope.strip():
        raise ValueError("missing repo_scope")
    return sha256(repo_scope.strip().encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class PreviewSession:
    session_id: str
    chat_id: str
    project_id: str
    repo_scope_hash: str
    builder_session_id: str
    revision: int
    status: str


def create_preview_session(*, session_id: str, chat_id: str, project_id: str,
                           repo_scope: str, builder_session_id: str,
                           revision: int = 0, status: str = "starting") -> PreviewSession:
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
        raise ValueError("invalid revision")
    if status not in _ALLOWED_STATUS:
        raise ValueError("invalid status")
    return PreviewSession(
        _stable_id(session_id, "session_id"), _stable_id(chat_id, "chat_id"),
        _stable_id(project_id, "project_id"), _scope_hash(repo_scope),
        _stable_id(builder_session_id, "builder_session_id"), revision, status,
    )


def assert_preview_access(session: PreviewSession, *, chat_id: str, project_id: str,
                          repo_scope: str, builder_session_id: str) -> None:
    expected = (
        _stable_id(chat_id, "chat_id"), _stable_id(project_id, "project_id"),
        _scope_hash(repo_scope), _stable_id(builder_session_id, "builder_session_id")
    )
    actual = (session.chat_id, session.project_id, session.repo_scope_hash, session.builder_session_id)
    if actual != expected:
        raise PermissionError("preview scope mismatch")


def transition_preview(session: PreviewSession, *, status: str, revision: int) -> PreviewSession:
    if status not in _ALLOWED_STATUS:
        raise ValueError("invalid status")
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < session.revision:
        raise ValueError("non-monotonic revision")
    if session.status in {"failed", "stopped"} and status != session.status:
        raise ValueError("terminal preview session")
    return PreviewSession(session.session_id, session.chat_id, session.project_id,
                          session.repo_scope_hash, session.builder_session_id, revision, status)
