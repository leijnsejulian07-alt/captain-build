"""Versioned, fail-closed persistence boundary for epoch-bound Captain memory.

This module deliberately performs no I/O. Captain's native storage owns bytes-at-rest;
this adapter only converts between a bounded inert snapshot and EpochBoundMemoryStore.
"""
from __future__ import annotations

from typing import Any

from memory_authority import MemoryAuthorityError
from memory_store_epoch_adapter import (
    EpochBoundMemoryStore, MAX_RECORDS_PER_AUTHORITY, _snapshot_json,
)

SNAPSHOT_VERSION = 1
MAX_AUTHORITIES_PER_SNAPSHOT = 256
MAX_RECORDS_PER_SNAPSHOT = MAX_AUTHORITIES_PER_SNAPSHOT * MAX_RECORDS_PER_AUTHORITY


def snapshot(store: EpochBoundMemoryStore) -> dict[str, Any]:
    records = tuple(store.all_records_for_test_only())
    if len(records) > MAX_RECORDS_PER_SNAPSHOT:
        raise MemoryAuthorityError("memory snapshot exceeds global record budget")
    authorities = {(r.authority.chat_id, r.authority.project_id,
                    r.authority.repo_scope_hash, r.authority.state_epoch) for r in records}
    if len(authorities) > MAX_AUTHORITIES_PER_SNAPSHOT:
        raise MemoryAuthorityError("memory snapshot exceeds authority budget")
    return {"version": SNAPSHOT_VERSION, "records": [
        {"authority": {"chat_id": r.authority.chat_id,
                       "project_id": r.authority.project_id,
                       "repo_scope_hash": r.authority.repo_scope_hash,
                       "state_epoch": r.authority.state_epoch},
         "key": r.key, "value": _snapshot_json(r.value),
         "provenance": dict(r.provenance)}
        for r in records
    ]}


def restore(data: Any) -> EpochBoundMemoryStore:
    """Atomically validate a snapshot into a fresh store; malformed state is rejected."""
    if type(data) is not dict or set(data) != {"version", "records"}:
        raise MemoryAuthorityError("memory snapshot fields invalid")
    if type(data["version"]) is not int or data["version"] != SNAPSHOT_VERSION:
        raise MemoryAuthorityError("unsupported memory snapshot version")
    records = data["records"]
    if type(records) is not list or len(records) > MAX_RECORDS_PER_SNAPSHOT:
        raise MemoryAuthorityError("memory snapshot record list invalid")
    candidate = EpochBoundMemoryStore()
    authorities: set[tuple[str, str, str, int]] = set()
    for item in records:
        if type(item) is not dict or set(item) != {"authority", "key", "value", "provenance"}:
            raise MemoryAuthorityError("memory snapshot record invalid")
        candidate.write_project(item["authority"], key=item["key"], value=item["value"],
                                provenance=item["provenance"])
        auth = item["authority"]
        authorities.add((auth["chat_id"], auth["project_id"],
                         auth["repo_scope_hash"], auth["state_epoch"]))
        if len(authorities) > MAX_AUTHORITIES_PER_SNAPSHOT:
            raise MemoryAuthorityError("memory snapshot exceeds authority budget")
    # Duplicate authority+key entries would otherwise silently collapse on restore.
    if sum(1 for _ in candidate.all_records_for_test_only()) != len(records):
        raise MemoryAuthorityError("memory snapshot contains duplicate record keys")
    return candidate
