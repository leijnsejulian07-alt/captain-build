"""Fail-closed memory/context envelope for Captain fallback work.

Parking-only: reconcile with the local Captain memory implementation before integration.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Any, Mapping

_ALLOWED_KINDS = {"project_fact", "project_decision", "user_preference", "shared_learning"}
_FORBIDDEN_KEYS = {"token", "api_key", "apikey", "authorization", "cookie", "password", "secret", "repo_scope", "chat_id"}
_MAX_PAYLOAD_KEYS = 32
_MAX_TEXT = 4096


def _stable_id(value: str, name: str) -> str:
    value = (value or "").strip()
    if not value or len(value) > 128 or any(c in value for c in "\\/\x00\r\n\t"):
        raise ValueError(f"invalid {name}")
    return value


def _scope_hash(project_id: str, repo_scope: str) -> str:
    project_id = _stable_id(project_id, "project_id")
    repo_scope = (repo_scope or "").strip()
    if not repo_scope or len(repo_scope) > 1024:
        raise ValueError("invalid repo_scope")
    return sha256(f"{project_id}\0{repo_scope}".encode()).hexdigest()


def _sanitize_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, Mapping) or len(payload) > _MAX_PAYLOAD_KEYS:
        raise ValueError("invalid payload")
    out: dict[str, Any] = {}
    for key, value in payload.items():
        if not isinstance(key, str) or not key or len(key) > 80:
            raise ValueError("invalid payload key")
        if key.lower() in _FORBIDDEN_KEYS:
            raise ValueError("forbidden payload key")
        if isinstance(value, str):
            if len(value) > _MAX_TEXT:
                raise ValueError("payload text too large")
            out[key] = value
        elif value is None or isinstance(value, (bool, int, float)):
            out[key] = value
        else:
            raise ValueError("unsupported payload value")
    return out


@dataclass(frozen=True)
class MemoryEnvelope:
    memory_id: str
    kind: str
    scope: str
    scope_hash: str | None
    payload: dict[str, Any]


def build_memory(*, memory_id: str, kind: str, payload: Mapping[str, Any], project_id: str | None = None, repo_scope: str | None = None) -> MemoryEnvelope:
    memory_id = _stable_id(memory_id, "memory_id")
    if kind not in _ALLOWED_KINDS:
        raise ValueError("unknown memory kind")
    clean = _sanitize_payload(payload)

    if kind == "shared_learning":
        if project_id or repo_scope:
            raise ValueError("shared learning must not carry project scope")
        scope, digest = "global", None
    else:
        if not project_id or not repo_scope:
            raise ValueError("project memory requires project_id + repo_scope")
        scope, digest = "project", _scope_hash(project_id, repo_scope)
    return MemoryEnvelope(memory_id, kind, scope, digest, clean)


def assert_memory_scope(memory: MemoryEnvelope, *, project_id: str | None = None, repo_scope: str | None = None) -> None:
    if memory.scope == "global":
        if memory.kind != "shared_learning":
            raise PermissionError("invalid global memory")
        return
    if not project_id or not repo_scope:
        raise PermissionError("missing project scope")
    if memory.scope_hash != _scope_hash(project_id, repo_scope):
        raise PermissionError("cross-project/repo memory access denied")


def promote_to_shared(memory: MemoryEnvelope, *, distilled_payload: Mapping[str, Any]) -> MemoryEnvelope:
    if memory.scope != "project":
        raise ValueError("only project memory can be distilled")
    clean = _sanitize_payload(distilled_payload)
    # Promotion is explicit and never copies project identifiers or raw payload automatically.
    return MemoryEnvelope(memory.memory_id + "-shared", "shared_learning", "global", None, clean)
