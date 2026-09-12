"""Fail-closed Captain memory/context authority envelope.

Fallback implementation for reconciliation with the live Captain runtime.
Project-scoped memory is bound to chat_id + project_id + repo_scope +
Project State epoch. Normal non-project chat context remains chat-scoped and
never acquires project/repository authority implicitly.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from hmac import compare_digest
from typing import Any, Mapping

_PROJECT_KINDS = {"project_fact", "project_decision", "project_context"}
_CHAT_KINDS = {"chat_context"}
_GLOBAL_KINDS = {"shared_learning"}
_ALLOWED_KINDS = _PROJECT_KINDS | _CHAT_KINDS | _GLOBAL_KINDS
_FORBIDDEN_KEYS = {
    "token", "api_key", "apikey", "authorization", "cookie", "password",
    "secret", "chat_id", "project_id", "repo_scope", "state_epoch",
}
_MAX_PAYLOAD_KEYS = 32
_MAX_TEXT = 4096


def _stable_id(value: str, name: str) -> str:
    value = (value or "").strip()
    if not value or len(value) > 160 or any(c in value for c in "\\/\x00\r\n\t"):
        raise ValueError(f"invalid {name}")
    return value


def _epoch(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError("invalid state_epoch")
    return value


def _project_digest(*, chat_id: str, project_id: str, repo_scope: str, state_epoch: int) -> str:
    chat_id = _stable_id(chat_id, "chat_id")
    project_id = _stable_id(project_id, "project_id")
    repo_scope = (repo_scope or "").strip()
    if not repo_scope or len(repo_scope) > 1024 or "\x00" in repo_scope:
        raise ValueError("invalid repo_scope")
    epoch = _epoch(state_epoch)
    raw = f"project\0{chat_id}\0{project_id}\0{repo_scope}\0{epoch}"
    return sha256(raw.encode("utf-8")).hexdigest()


def _chat_digest(*, chat_id: str) -> str:
    chat_id = _stable_id(chat_id, "chat_id")
    return sha256(f"chat\0{chat_id}".encode("utf-8")).hexdigest()


def _sanitize_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, Mapping) or len(payload) > _MAX_PAYLOAD_KEYS:
        raise ValueError("invalid payload")
    out: dict[str, Any] = {}
    for key, value in payload.items():
        if not isinstance(key, str) or not key or len(key) > 80:
            raise ValueError("invalid payload key")
        if key.lower() in _FORBIDDEN_KEYS:
            raise ValueError("scope/secrets must not be embedded in payload")
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
    authority_digest: str | None
    payload: dict[str, Any]

    def public_metadata(self) -> dict[str, Any]:
        """Secret- and identifier-minimized projection for logs/UI."""
        return {
            "memory_id": self.memory_id,
            "kind": self.kind,
            "scope": self.scope,
            "authority_bound": self.authority_digest is not None,
        }


def build_memory(
    *,
    memory_id: str,
    kind: str,
    payload: Mapping[str, Any],
    chat_id: str | None = None,
    project_id: str | None = None,
    repo_scope: str | None = None,
    state_epoch: int | None = None,
) -> MemoryEnvelope:
    memory_id = _stable_id(memory_id, "memory_id")
    if kind not in _ALLOWED_KINDS:
        raise ValueError("unknown memory kind")
    clean = _sanitize_payload(payload)

    if kind in _PROJECT_KINDS:
        if chat_id is None or project_id is None or repo_scope is None or state_epoch is None:
            raise ValueError("project memory requires chat_id + project_id + repo_scope + state_epoch")
        digest = _project_digest(
            chat_id=chat_id,
            project_id=project_id,
            repo_scope=repo_scope,
            state_epoch=state_epoch,
        )
        return MemoryEnvelope(memory_id, kind, "project", digest, clean)

    if kind in _CHAT_KINDS:
        if chat_id is None:
            raise ValueError("chat context requires chat_id")
        if project_id is not None or repo_scope is not None or state_epoch is not None:
            raise ValueError("normal chat context must not carry project authority")
        return MemoryEnvelope(memory_id, kind, "chat", _chat_digest(chat_id=chat_id), clean)

    if any(value is not None for value in (chat_id, project_id, repo_scope, state_epoch)):
        raise ValueError("shared learning must be explicitly unscoped")
    return MemoryEnvelope(memory_id, kind, "global", None, clean)


def assert_memory_access(
    memory: MemoryEnvelope,
    *,
    chat_id: str | None = None,
    project_id: str | None = None,
    repo_scope: str | None = None,
    state_epoch: int | None = None,
) -> None:
    if memory.scope == "project":
        if chat_id is None or project_id is None or repo_scope is None or state_epoch is None:
            raise PermissionError("missing current project authority")
        expected = _project_digest(
            chat_id=chat_id,
            project_id=project_id,
            repo_scope=repo_scope,
            state_epoch=state_epoch,
        )
        if memory.authority_digest is None or not compare_digest(memory.authority_digest, expected):
            raise PermissionError("stale or foreign project memory denied")
        return

    if memory.scope == "chat":
        if chat_id is None:
            raise PermissionError("missing current chat authority")
        expected = _chat_digest(chat_id=chat_id)
        if memory.authority_digest is None or not compare_digest(memory.authority_digest, expected):
            raise PermissionError("foreign chat context denied")
        if any(value is not None for value in (project_id, repo_scope, state_epoch)):
            raise PermissionError("chat-only memory cannot satisfy project authority")
        return

    if memory.scope == "global" and memory.kind == "shared_learning" and memory.authority_digest is None:
        return
    raise PermissionError("invalid memory envelope")


def distill_shared(memory: MemoryEnvelope, *, distilled_payload: Mapping[str, Any]) -> MemoryEnvelope:
    """Explicitly create non-project-specific learning; never copy raw project payload."""
    if memory.scope != "project":
        raise ValueError("only project memory can be distilled")
    clean = _sanitize_payload(distilled_payload)
    return MemoryEnvelope(memory.memory_id + "-shared", "shared_learning", "global", None, clean)
