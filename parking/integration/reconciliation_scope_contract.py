from __future__ import annotations

import copy
import hashlib
import json
import re

SCHEMA_VERSION = 1
DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
MAX_SCOPE_VALUE = 512


def _validate_scope_value(name: str, value: object) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a string")
    normalized = value.strip()
    if not normalized or len(normalized) > MAX_SCOPE_VALUE:
        raise ValueError(f"invalid {name}")
    if "\x00" in normalized:
        raise ValueError(f"invalid {name}")
    return normalized


def compute_scope_digest(*, chat_id: str, project_id: str, repo_scope: str) -> str:
    payload = {
        "chat_id": _validate_scope_value("chat_id", chat_id),
        "project_id": _validate_scope_value("project_id", project_id),
        "repo_scope": _validate_scope_value("repo_scope", repo_scope),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def bind_state(state: dict, *, chat_id: str, project_id: str, repo_scope: str) -> dict:
    if not isinstance(state, dict):
        raise ValueError("reconciliation state must be an object")
    return {
        "schema_version": SCHEMA_VERSION,
        "scope_digest": compute_scope_digest(
            chat_id=chat_id, project_id=project_id, repo_scope=repo_scope
        ),
        "state": copy.deepcopy(state),
    }


def validate_scoped_state(
    envelope: dict, *, chat_id: str, project_id: str, repo_scope: str
) -> None:
    if not isinstance(envelope, dict) or set(envelope) != {
        "schema_version",
        "scope_digest",
        "state",
    }:
        raise ValueError("invalid scoped reconciliation envelope")
    if envelope.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported scoped reconciliation envelope schema")
    digest = envelope.get("scope_digest")
    if not isinstance(digest, str) or not DIGEST_RE.fullmatch(digest):
        raise ValueError("invalid reconciliation scope digest")
    expected = compute_scope_digest(
        chat_id=chat_id, project_id=project_id, repo_scope=repo_scope
    )
    if digest != expected:
        raise ValueError("reconciliation scope mismatch")
    if not isinstance(envelope.get("state"), dict):
        raise ValueError("reconciliation state must be an object")


def unwrap_state(
    envelope: dict, *, chat_id: str, project_id: str, repo_scope: str
) -> dict:
    validate_scoped_state(
        envelope, chat_id=chat_id, project_id=project_id, repo_scope=repo_scope
    )
    return copy.deepcopy(envelope["state"])
