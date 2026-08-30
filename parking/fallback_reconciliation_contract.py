"""Fail-closed reconciliation contract for Captain fallback work.

Parking-only: no runtime integration. Designed to prevent stale, duplicate, cross-repo,
or dependency-order mistakes when GitHub fallback work is reconciled locally.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re
from typing import Iterable

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
_SHA = re.compile(r"^[0-9a-f]{40}$")
_ALLOWED = {"pending", "verified", "rejected", "integrated"}


def _clean_id(value: str, field: str) -> str:
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise ValueError(f"invalid {field}")
    return value


def _scope_hash(repo_scope: str) -> str:
    if not isinstance(repo_scope, str) or not repo_scope.strip():
        raise ValueError("repo_scope required")
    return hashlib.sha256(repo_scope.strip().encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class FallbackCheckpoint:
    checkpoint_id: str
    source_ref: str
    source_sha: str
    repo_scope_hash: str
    local_base_sha: str
    dependencies: tuple[str, ...] = ()
    status: str = "pending"

    @classmethod
    def create(cls, *, checkpoint_id: str, source_ref: str, source_sha: str,
               repo_scope: str, local_base_sha: str, dependencies: Iterable[str] = (),
               status: str = "pending") -> "FallbackCheckpoint":
        cid = _clean_id(checkpoint_id, "checkpoint_id")
        ref = _clean_id(source_ref, "source_ref")
        if not _SHA.fullmatch(source_sha or "") or not _SHA.fullmatch(local_base_sha or ""):
            raise ValueError("invalid sha")
        deps = tuple(_clean_id(x, "dependency") for x in dependencies)
        if cid in deps or len(deps) != len(set(deps)) or len(deps) > 32:
            raise ValueError("invalid dependencies")
        if status not in _ALLOWED:
            raise ValueError("invalid status")
        return cls(cid, ref, source_sha, _scope_hash(repo_scope), local_base_sha, deps, status)


def can_reconcile(checkpoint: FallbackCheckpoint, *, repo_scope: str,
                  actual_local_base_sha: str, completed: Iterable[str]) -> bool:
    """Return True only when scope/base/dependencies exactly match.

    A moved local base must be reviewed explicitly instead of silently applying stale work.
    """
    if checkpoint.status not in {"pending", "verified"}:
        return False
    if checkpoint.repo_scope_hash != _scope_hash(repo_scope):
        return False
    if actual_local_base_sha != checkpoint.local_base_sha:
        return False
    done = set(completed)
    return all(dep in done for dep in checkpoint.dependencies)


def transition(checkpoint: FallbackCheckpoint, new_status: str) -> FallbackCheckpoint:
    allowed = {
        "pending": {"verified", "rejected"},
        "verified": {"integrated", "rejected"},
        "rejected": set(),
        "integrated": set(),
    }
    if new_status not in allowed[checkpoint.status]:
        raise ValueError("invalid transition")
    return FallbackCheckpoint(**{**checkpoint.__dict__, "status": new_status})
