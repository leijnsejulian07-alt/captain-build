"""Fail-closed Project State envelope contract for Captain parking work."""
from __future__ import annotations
import hashlib
import re
from dataclasses import dataclass
from typing import Any, Mapping

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
ALLOWED_KINDS = frozenset({"research", "plan", "builder", "review", "task", "connector"})
MAX_PAYLOAD_KEYS = 32


def _need_id(name: str, value: str) -> str:
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise ValueError(f"invalid {name}")
    return value


def scope_hash(repo_scope: str) -> str:
    if not isinstance(repo_scope, str) or not repo_scope.strip():
        raise ValueError("repo_scope required")
    return hashlib.sha256(repo_scope.strip().casefold().encode()).hexdigest()


@dataclass(frozen=True)
class ProjectStateEnvelope:
    schema_version: int
    project_id: str
    repo_scope_hash: str
    kind: str
    revision: int
    payload: Mapping[str, Any]


def make_envelope(*, project_id: str, repo_scope: str, kind: str,
                  revision: int, payload: Mapping[str, Any]) -> ProjectStateEnvelope:
    project_id = _need_id("project_id", project_id)
    if kind not in ALLOWED_KINDS:
        raise ValueError("unknown state kind")
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 0:
        raise ValueError("invalid revision")
    if not isinstance(payload, Mapping) or len(payload) > MAX_PAYLOAD_KEYS:
        raise ValueError("invalid payload")
    forbidden = {"chat_id", "repo_scope", "token", "api_key", "authorization", "cookie"}
    if forbidden.intersection(str(k).casefold() for k in payload):
        raise ValueError("forbidden payload key")
    return ProjectStateEnvelope(1, project_id, scope_hash(repo_scope), kind, revision, dict(payload))


def assert_same_scope(envelope: ProjectStateEnvelope, *, project_id: str, repo_scope: str) -> None:
    if envelope.project_id != _need_id("project_id", project_id):
        raise PermissionError("project scope mismatch")
    if envelope.repo_scope_hash != scope_hash(repo_scope):
        raise PermissionError("repo scope mismatch")
