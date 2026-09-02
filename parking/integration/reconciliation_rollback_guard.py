from __future__ import annotations

import hashlib
import json
import re

SCHEMA_VERSION = 1
DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")


def _digest(value: object) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _validate_generation(value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError("invalid reconciliation generation")
    return value


def issue_guard(envelope: dict, *, scope_digest: str, generation: int) -> dict:
    if not isinstance(envelope, dict):
        raise ValueError("scoped envelope must be an object")
    if not isinstance(scope_digest, str) or not DIGEST_RE.fullmatch(scope_digest):
        raise ValueError("invalid scope digest")
    generation = _validate_generation(generation)
    return {
        "schema_version": SCHEMA_VERSION,
        "scope_digest": scope_digest,
        "generation": generation,
        "envelope_digest": _digest(envelope),
    }


def validate_guard_shape(guard: dict, *, expected_scope_digest: str) -> None:
    if not isinstance(guard, dict) or set(guard) != {
        "schema_version", "scope_digest", "generation", "envelope_digest"
    }:
        raise ValueError("invalid reconciliation rollback guard")
    if guard["schema_version"] != SCHEMA_VERSION:
        raise ValueError("unsupported reconciliation rollback guard schema")
    if guard["scope_digest"] != expected_scope_digest:
        raise ValueError("reconciliation rollback scope mismatch")
    _validate_generation(guard["generation"])
    digest = guard["envelope_digest"]
    if not isinstance(digest, str) or not DIGEST_RE.fullmatch(digest):
        raise ValueError("invalid reconciliation envelope digest")


def validate_loaded(
    envelope: dict,
    guard: dict,
    *,
    expected_scope_digest: str,
    minimum_generation: int,
) -> None:
    validate_guard_shape(guard, expected_scope_digest=expected_scope_digest)
    minimum_generation = _validate_generation(minimum_generation)
    if guard["generation"] < minimum_generation:
        raise ValueError("stale reconciliation state rollback")
    if not isinstance(envelope, dict) or guard["envelope_digest"] != _digest(envelope):
        raise ValueError("reconciliation envelope digest mismatch")


def advance_guard(
    previous_guard: dict,
    next_envelope: dict,
    *,
    expected_scope_digest: str,
    next_generation: int,
) -> dict:
    validate_guard_shape(previous_guard, expected_scope_digest=expected_scope_digest)
    next_generation = _validate_generation(next_generation)
    if next_generation != previous_guard["generation"] + 1:
        raise ValueError("reconciliation generation must advance exactly once")
    return issue_guard(
        next_envelope,
        scope_digest=expected_scope_digest,
        generation=next_generation,
    )
