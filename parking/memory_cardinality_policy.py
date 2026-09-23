"""Deterministic cardinality policy for Captain project memory.

This is a dependency-free parking primitive. It prevents repeated writes from
silently inflating assembled context and never evicts data across authority walls.
"""
from __future__ import annotations

from typing import Iterable

from memory_authority import MemoryAuthority, MemoryAuthorityError
from memory_store_epoch_adapter import MemoryRecord

MAX_RECORDS_PER_AUTHORITY = 2_048


def apply_write(records: Iterable[MemoryRecord], incoming: MemoryRecord) -> tuple[MemoryRecord, ...]:
    """Upsert one key inside the exact authority, or reject a full authority.

    Other chat/project/repo/epoch authorities are preserved byte-for-byte. A
    repeated key is a deterministic replacement, not another context entry.
    """
    auth = MemoryAuthority.parse({
        "chat_id": incoming.authority.chat_id,
        "project_id": incoming.authority.project_id,
        "repo_scope_hash": incoming.authority.repo_scope_hash,
        "state_epoch": incoming.authority.state_epoch,
    })
    current = tuple(records)
    matching = [i for i, record in enumerate(current) if auth.permits(record.authority)]
    for index in matching:
        if current[index].key == incoming.key:
            updated = list(current)
            updated[index] = incoming
            return tuple(updated)
    if len(matching) >= MAX_RECORDS_PER_AUTHORITY:
        raise MemoryAuthorityError("project memory authority exceeds record budget")
    return current + (incoming,)
