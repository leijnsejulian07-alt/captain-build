"""Captain project-memory authority primitive.

Parking implementation: provider-neutral, no I/O and no third-party runtime.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Mapping

_HASH = re.compile(r"^[0-9a-f]{64}$")


class MemoryAuthorityError(ValueError):
    """Raised when project-memory authority is incomplete or malformed."""


@dataclass(frozen=True, slots=True)
class MemoryAuthority:
    chat_id: str
    project_id: str
    repo_scope_hash: str
    state_epoch: int

    @classmethod
    def parse(cls, value: Mapping[str, Any]) -> "MemoryAuthority":
        if not isinstance(value, Mapping):
            raise MemoryAuthorityError("authority must be a mapping")
        allowed = {"chat_id", "project_id", "repo_scope_hash", "state_epoch"}
        if set(value) != allowed:
            raise MemoryAuthorityError("authority fields must match the canonical tuple")
        chat_id = value["chat_id"]
        project_id = value["project_id"]
        repo_hash = value["repo_scope_hash"]
        epoch = value["state_epoch"]
        if not isinstance(chat_id, str) or not chat_id.strip():
            raise MemoryAuthorityError("chat_id required")
        if not isinstance(project_id, str) or not project_id.strip():
            raise MemoryAuthorityError("project_id required")
        if not isinstance(repo_hash, str) or not _HASH.fullmatch(repo_hash):
            raise MemoryAuthorityError("repo_scope_hash must be lowercase sha256")
        if isinstance(epoch, bool) or not isinstance(epoch, int) or epoch < 1:
            raise MemoryAuthorityError("state_epoch must be an integer >= 1")
        return cls(chat_id.strip(), project_id.strip(), repo_hash, epoch)

    def permits(self, record: "MemoryAuthority") -> bool:
        return self == record


def project_memory_visible(record: Mapping[str, Any], current: Mapping[str, Any]) -> bool:
    """Fail closed: malformed/stale authority is never visible."""
    try:
        return MemoryAuthority.parse(record) == MemoryAuthority.parse(current)
    except (MemoryAuthorityError, TypeError):
        return False
