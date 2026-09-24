"""Captain project-memory authority primitive.

Parking implementation: provider-neutral, no I/O and no third-party runtime.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Mapping

_HASH = re.compile(r"^[0-9a-f]{64}$")
_MAX_ID_CHARS = 256


class MemoryAuthorityError(ValueError):
    """Raised when project-memory authority is incomplete or malformed."""


def _plain_id(value: Any, field: str) -> str:
    # Authority scalars are hostile input too. str subclasses may override
    # strip/equality/hash hooks, so reject them before any operation.
    if type(value) is not str:
        raise MemoryAuthorityError(f"{field} must be a plain string")
    normalized = value.strip()
    if not normalized:
        raise MemoryAuthorityError(f"{field} required")
    if len(normalized) > _MAX_ID_CHARS:
        raise MemoryAuthorityError(f"{field} too large")
    return normalized


@dataclass(frozen=True, slots=True)
class MemoryAuthority:
    chat_id: str
    project_id: str
    repo_scope_hash: str
    state_epoch: int

    @classmethod
    def parse(cls, value: Mapping[str, Any]) -> "MemoryAuthority":
        # Authority crosses a trust boundary. Accept only inert builtins:
        # arbitrary mappings/scalar subclasses may execute caller code while
        # Captain is validating Project State.
        if type(value) is not dict:
            raise MemoryAuthorityError("authority must be a builtin dict")
        allowed = {"chat_id", "project_id", "repo_scope_hash", "state_epoch"}
        if set(value) != allowed:
            raise MemoryAuthorityError("authority fields must match the canonical tuple")
        chat_id = _plain_id(value["chat_id"], "chat_id")
        project_id = _plain_id(value["project_id"], "project_id")
        repo_hash = value["repo_scope_hash"]
        epoch = value["state_epoch"]
        if type(repo_hash) is not str or not _HASH.fullmatch(repo_hash):
            raise MemoryAuthorityError("repo_scope_hash must be plain lowercase sha256")
        if type(epoch) is not int or epoch < 1:
            raise MemoryAuthorityError("state_epoch must be a plain integer >= 1")
        return cls(chat_id, project_id, repo_hash, epoch)

    def permits(self, record: "MemoryAuthority") -> bool:
        return self == record


def project_memory_visible(record: Mapping[str, Any], current: Mapping[str, Any]) -> bool:
    """Fail closed: malformed/stale authority is never visible."""
    try:
        return MemoryAuthority.parse(record) == MemoryAuthority.parse(current)
    except (MemoryAuthorityError, TypeError):
        return False
