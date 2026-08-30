"""Fail-closed, secret-minimizing observability contract for Captain."""
from __future__ import annotations
from dataclasses import dataclass
from hashlib import sha256
import re

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,95}$")
_ALLOWED_KINDS = {"router", "research", "builder", "preview", "job", "connector", "doctor"}
_ALLOWED_LEVELS = {"debug", "info", "warning", "error"}
_ALLOWED_FIELDS = {"status", "duration_ms", "attempt", "provider_id", "model_id", "action", "reason_code", "count", "revision"}
_SENSITIVE = {"prompt", "content", "messages", "token", "api_key", "apikey", "secret", "password", "cookie", "authorization", "repo_scope", "path", "cwd", "url"}


def _valid_id(value: str) -> bool:
    return isinstance(value, str) and bool(_ID.fullmatch(value)) and ".." not in value


def _scope_hash(repo_scope: str) -> str:
    if not isinstance(repo_scope, str) or not repo_scope.strip():
        raise ValueError("repo_scope required")
    return sha256(repo_scope.strip().encode()).hexdigest()


def _clean_fields(fields: dict) -> tuple[tuple[str, object], ...]:
    if not isinstance(fields, dict) or len(fields) > 12:
        raise ValueError("invalid observability fields")
    out = []
    for key, value in fields.items():
        if not isinstance(key, str) or key.lower() in _SENSITIVE or key not in _ALLOWED_FIELDS:
            raise ValueError("unsupported or sensitive observability field")
        if isinstance(value, bool):
            clean = value
        elif isinstance(value, int):
            if abs(value) > 10_000_000:
                raise ValueError("integer field out of bounds")
            clean = value
        elif isinstance(value, str):
            if len(value) > 160 or any(c in value for c in "\r\n\x00"):
                raise ValueError("string field out of bounds")
            clean = value
        else:
            raise ValueError("unsupported observability value")
        out.append((key, clean))
    return tuple(sorted(out))


@dataclass(frozen=True)
class ObservabilityEvent:
    event_id: str
    kind: str
    level: str
    chat_id_hash: str
    project_id_hash: str
    repo_scope_hash: str
    fields: tuple[tuple[str, object], ...]


def create_event(*, event_id: str, kind: str, level: str, chat_id: str,
                 project_id: str, repo_scope: str, fields: dict) -> ObservabilityEvent:
    if not _valid_id(event_id) or not _valid_id(chat_id) or not _valid_id(project_id):
        raise ValueError("invalid scoped id")
    if kind not in _ALLOWED_KINDS or level not in _ALLOWED_LEVELS:
        raise ValueError("unsupported observability kind or level")
    return ObservabilityEvent(
        event_id=event_id,
        kind=kind,
        level=level,
        chat_id_hash=sha256(chat_id.encode()).hexdigest(),
        project_id_hash=sha256(project_id.encode()).hexdigest(),
        repo_scope_hash=_scope_hash(repo_scope),
        fields=_clean_fields(fields),
    )


def same_scope(event: ObservabilityEvent, *, chat_id: str, project_id: str, repo_scope: str) -> bool:
    try:
        return (
            event.chat_id_hash == sha256(chat_id.encode()).hexdigest()
            and event.project_id_hash == sha256(project_id.encode()).hexdigest()
            and event.repo_scope_hash == _scope_hash(repo_scope)
        )
    except (AttributeError, TypeError, ValueError):
        return False


def public_dict(event: ObservabilityEvent) -> dict:
    return {
        "event_id": event.event_id,
        "kind": event.kind,
        "level": event.level,
        "chat_id_hash": event.chat_id_hash,
        "project_id_hash": event.project_id_hash,
        "repo_scope_hash": event.repo_scope_hash,
        "fields": dict(event.fields),
    }
