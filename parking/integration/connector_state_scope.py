from __future__ import annotations

from hashlib import sha256
import hmac
import json


class ConnectorStateScopeError(ValueError):
    pass


def _text(value: object, name: str, max_len: int) -> str:
    if not isinstance(value, str) or not value or len(value) > max_len or value.strip() != value:
        raise ConnectorStateScopeError(f"invalid {name}")
    return value


def _scope(*, chat_id: object, project_id: object, repo_scope: object) -> dict:
    return {
        "chat_id": _text(chat_id, "chat_id", 120),
        "project_id": _text(project_id, "project_id", 120),
        "repo_scope": _text(repo_scope, "repo_scope", 300),
    }


def _canonical_copy(value: dict) -> dict:
    if not isinstance(value, dict):
        raise ConnectorStateScopeError("invalid connector state")
    try:
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
        decoded = json.loads(encoded)
    except (TypeError, ValueError) as exc:
        raise ConnectorStateScopeError("non-canonical connector state") from exc
    if not isinstance(decoded, dict):
        raise ConnectorStateScopeError("invalid connector state")
    return decoded


def _digest(scope: dict, state: dict) -> str:
    payload = json.dumps(
        {"scope": scope, "state": state},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    return sha256(payload).hexdigest()


def bind_connector_state(
    state: dict,
    *,
    chat_id: str,
    project_id: str,
    repo_scope: str,
) -> dict:
    """Bind canonical connector state to one exact Captain execution wall.

    This envelope is deliberately secret-agnostic: caller-owned connector state must contain
    metadata/status only. Secret material belongs in the provider's credential store and must
    never be copied into this persisted state.
    """
    clean_state = _canonical_copy(state)
    if clean_state.get("project_id") != project_id:
        raise ConnectorStateScopeError("connector project mismatch")
    if any(key in clean_state for key in ("secret", "secrets", "token", "access_token", "refresh_token", "api_key", "password")):
        raise ConnectorStateScopeError("secret-like field forbidden")
    scope = _scope(chat_id=chat_id, project_id=project_id, repo_scope=repo_scope)
    return {
        "schema_version": 1,
        "scope": scope,
        "state": clean_state,
        "binding_digest": _digest(scope, clean_state),
    }


def unwrap_connector_state(
    envelope: dict,
    *,
    chat_id: str,
    project_id: str,
    repo_scope: str,
) -> dict:
    if not isinstance(envelope, dict) or set(envelope) != {
        "schema_version",
        "scope",
        "state",
        "binding_digest",
    }:
        raise ConnectorStateScopeError("invalid envelope")
    if envelope["schema_version"] != 1:
        raise ConnectorStateScopeError("schema")

    expected_scope = _scope(chat_id=chat_id, project_id=project_id, repo_scope=repo_scope)
    if envelope["scope"] != expected_scope:
        raise ConnectorStateScopeError("scope mismatch")

    state = _canonical_copy(envelope["state"])
    if state.get("project_id") != project_id:
        raise ConnectorStateScopeError("connector project mismatch")
    if any(key in state for key in ("secret", "secrets", "token", "access_token", "refresh_token", "api_key", "password")):
        raise ConnectorStateScopeError("secret-like field forbidden")

    actual = envelope["binding_digest"]
    expected = _digest(expected_scope, state)
    if not isinstance(actual, str) or not hmac.compare_digest(actual, expected):
        raise ConnectorStateScopeError("binding mismatch")
    return state
