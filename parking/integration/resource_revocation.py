from __future__ import annotations

import hashlib
import json
import re
from typing import Mapping

SCHEMA_VERSION = 1
MAX_GENERATION = 2**63 - 1
MAX_REVOKED_AT = 2**63 - 1
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_SCOPE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_RESOURCE_KIND_RE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_RESOURCE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,191}$")
_ALLOWED_REASONS = {
    "manual",
    "plugin_disabled",
    "connector_disconnected",
    "project_reset",
    "resource_stopped",
    "security_reset",
}


def _validate_positive_int(name: str, value: object, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1 or value > maximum:
        raise ValueError(f"invalid {name}")
    return value


def _validate_id(name: str, value: object, pattern: re.Pattern[str]) -> str:
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise ValueError(f"invalid {name}")
    return value


def _validate_digest(value: object) -> str:
    if not isinstance(value, str) or not _DIGEST_RE.fullmatch(value):
        raise ValueError("invalid binding_digest")
    return value


def _payload_digest(payload: Mapping[str, object]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def create_revocation(
    *,
    binding_digest: str,
    principal_id: str,
    resource_kind: str,
    resource_id: str,
    resource_generation: int,
    revoked_at: int,
    reason: str,
) -> dict[str, object]:
    digest = _validate_digest(binding_digest)
    principal = _validate_id("principal_id", principal_id, _SCOPE_ID_RE)
    kind = _validate_id("resource_kind", resource_kind, _RESOURCE_KIND_RE)
    resource = _validate_id("resource_id", resource_id, _RESOURCE_ID_RE)
    generation = _validate_positive_int("resource_generation", resource_generation, MAX_GENERATION)
    timestamp = _validate_positive_int("revoked_at", revoked_at, MAX_REVOKED_AT)
    if reason not in _ALLOWED_REASONS:
        raise ValueError("invalid revocation reason")

    payload = {
        "schema_version": SCHEMA_VERSION,
        "binding_digest": digest,
        "principal_id": principal,
        "resource_kind": kind,
        "resource_id": resource,
        "resource_generation": generation,
        "revoked_at": timestamp,
        "reason": reason,
    }
    return {**payload, "revocation_digest": _payload_digest(payload)}


def validate_revocation(
    revocation: Mapping[str, object],
    *,
    expected_binding_digest: str,
    expected_principal_id: str,
    expected_resource_kind: str,
    expected_resource_id: str,
    expected_resource_generation: int,
) -> dict[str, object]:
    required = {
        "schema_version",
        "binding_digest",
        "principal_id",
        "resource_kind",
        "resource_id",
        "resource_generation",
        "revoked_at",
        "reason",
        "revocation_digest",
    }
    if not isinstance(revocation, Mapping) or set(revocation) != required:
        raise ValueError("invalid resource revocation")
    if revocation.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported resource revocation schema")

    expected_digest = _validate_digest(expected_binding_digest)
    expected_principal = _validate_id("expected_principal_id", expected_principal_id, _SCOPE_ID_RE)
    expected_kind = _validate_id("expected_resource_kind", expected_resource_kind, _RESOURCE_KIND_RE)
    expected_id = _validate_id("expected_resource_id", expected_resource_id, _RESOURCE_ID_RE)
    expected_generation = _validate_positive_int(
        "expected_resource_generation", expected_resource_generation, MAX_GENERATION
    )

    binding_digest = _validate_digest(revocation.get("binding_digest"))
    principal = _validate_id("principal_id", revocation.get("principal_id"), _SCOPE_ID_RE)
    kind = _validate_id("resource_kind", revocation.get("resource_kind"), _RESOURCE_KIND_RE)
    resource_id = _validate_id("resource_id", revocation.get("resource_id"), _RESOURCE_ID_RE)
    generation = _validate_positive_int("resource_generation", revocation.get("resource_generation"), MAX_GENERATION)
    revoked_at = _validate_positive_int("revoked_at", revocation.get("revoked_at"), MAX_REVOKED_AT)
    reason = revocation.get("reason")
    if reason not in _ALLOWED_REASONS:
        raise ValueError("invalid revocation reason")
    revocation_digest = revocation.get("revocation_digest")
    if not isinstance(revocation_digest, str) or not _DIGEST_RE.fullmatch(revocation_digest):
        raise ValueError("invalid revocation_digest")

    payload = {
        "schema_version": SCHEMA_VERSION,
        "binding_digest": binding_digest,
        "principal_id": principal,
        "resource_kind": kind,
        "resource_id": resource_id,
        "resource_generation": generation,
        "revoked_at": revoked_at,
        "reason": reason,
    }
    if revocation_digest != _payload_digest(payload):
        raise ValueError("resource revocation was modified")

    if binding_digest != expected_digest:
        raise PermissionError("revocation binding mismatch")
    if principal != expected_principal:
        raise PermissionError("revocation principal mismatch")
    if kind != expected_kind:
        raise PermissionError("revocation resource kind mismatch")
    if resource_id != expected_id:
        raise PermissionError("revocation resource id mismatch")
    if generation != expected_generation:
        raise PermissionError("revocation generation mismatch")
    return dict(revocation)


def assert_not_revoked(
    revocation: Mapping[str, object] | None,
    *,
    expected_binding_digest: str,
    expected_principal_id: str,
    expected_resource_kind: str,
    expected_resource_id: str,
    expected_resource_generation: int,
) -> None:
    if revocation is None:
        return
    validate_revocation(
        revocation,
        expected_binding_digest=expected_binding_digest,
        expected_principal_id=expected_principal_id,
        expected_resource_kind=expected_resource_kind,
        expected_resource_id=expected_resource_id,
        expected_resource_generation=expected_resource_generation,
    )
    raise PermissionError("resource has been revoked")
