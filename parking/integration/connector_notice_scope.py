from __future__ import annotations

from hashlib import sha256
import hmac
import json


class ScopeError(ValueError):
    pass


def _text(value: object, name: str, max_len: int = 200) -> str:
    if not isinstance(value, str) or not value or len(value) > max_len or value.strip() != value:
        raise ScopeError(f"invalid {name}")
    return value


def _scope(chat_id: object, project_id: object, repo_scope: object) -> dict:
    return {
        "chat_id": _text(chat_id, "chat_id", 120),
        "project_id": _text(project_id, "project_id", 120),
        "repo_scope": _text(repo_scope, "repo_scope", 300),
    }


def _digest(scope: dict, notice: dict) -> str:
    payload = json.dumps(
        {"scope": scope, "notice": notice},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return sha256(payload).hexdigest()


def bind_notice(notice: dict, *, chat_id: str, project_id: str, repo_scope: str) -> dict:
    if not isinstance(notice, dict):
        raise ScopeError("invalid notice")
    if notice.get("project_id") != project_id:
        raise ScopeError("notice project mismatch")
    if "secret_fields" not in notice or notice["secret_fields"] != []:
        raise ScopeError("notice secret contract")
    scope = _scope(chat_id, project_id, repo_scope)
    clean_notice = json.loads(json.dumps(notice, sort_keys=True))
    return {
        "schema_version": 1,
        "scope": scope,
        "notice": clean_notice,
        "binding_digest": _digest(scope, clean_notice),
    }


def unwrap_notice(envelope: dict, *, chat_id: str, project_id: str, repo_scope: str) -> dict:
    if not isinstance(envelope, dict) or set(envelope) != {"schema_version", "scope", "notice", "binding_digest"}:
        raise ScopeError("invalid envelope")
    if envelope["schema_version"] != 1:
        raise ScopeError("schema")
    expected_scope = _scope(chat_id, project_id, repo_scope)
    if envelope["scope"] != expected_scope:
        raise ScopeError("scope mismatch")
    notice = envelope["notice"]
    if not isinstance(notice, dict) or notice.get("project_id") != project_id:
        raise ScopeError("notice mismatch")
    if notice.get("secret_fields") != []:
        raise ScopeError("notice secret contract")
    expected = _digest(expected_scope, notice)
    actual = envelope["binding_digest"]
    if not isinstance(actual, str) or not hmac.compare_digest(actual, expected):
        raise ScopeError("binding mismatch")
    return json.loads(json.dumps(notice, sort_keys=True))
