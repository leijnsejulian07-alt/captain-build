from __future__ import annotations

import hashlib
import hmac
import json
import re
from typing import Mapping

from parking.integration.builder_session_contract import authorize_builder_action
from parking.integration.scope_contract import ScopeKey, parse_scope

SCHEMA_VERSION = 1
_AUTHORITY = "captain"
_BACKEND_RE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")

# Bounded adapters only. These are execution backends behind Captain, never alternate
# routers, memory authorities, project-state owners, or user-facing control planes.
BACKENDS: dict[str, dict[str, object]] = {
    "openbuilder": {
        "adapter_kind": "embedded",
        "optional": False,
        "remote_capable": False,
    },
    "freebuff": {
        "adapter_kind": "sdk",
        "optional": True,
        "remote_capable": True,
    },
    "opencode": {
        "adapter_kind": "process",
        "optional": True,
        "remote_capable": True,
    },
}


def _bool(value: object, field: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"invalid {field}")
    return value


def _digest(value: object, field: str) -> str:
    if not isinstance(value, str) or not _DIGEST_RE.fullmatch(value):
        raise ValueError(f"invalid {field}")
    return value


def _backend(backend_id: object) -> tuple[str, Mapping[str, object]]:
    if not isinstance(backend_id, str) or not _BACKEND_RE.fullmatch(backend_id):
        raise ValueError("invalid backend_id")
    descriptor = BACKENDS.get(backend_id)
    if descriptor is None:
        raise PermissionError("builder backend is not allowlisted")
    return backend_id, descriptor


def _binding(
    scope: ScopeKey,
    *,
    session_binding: str,
    state_epoch: int,
    backend_id: str,
    adapter_kind: str,
    capability: str,
    execution_mode: str,
) -> str:
    payload = {
        "schema_version": SCHEMA_VERSION,
        "authority": _AUTHORITY,
        "scope": scope.as_dict(),
        "session_binding": session_binding,
        "state_epoch": state_epoch,
        "backend_id": backend_id,
        "adapter_kind": adapter_kind,
        "capability": capability,
        "execution_mode": execution_mode,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def issue_builder_backend_dispatch(
    session: Mapping[str, object],
    *,
    chat_id: str,
    project_id: str,
    repo_scope: str,
    session_id: str,
    repo_head: str,
    worktree_digest: str,
    state_epoch: int,
    capability: str,
    backend_id: str = "openbuilder",
    installed: bool,
    enabled: bool,
    ready: bool,
    allow_optional_backend: bool = False,
    execution_mode: str = "local",
    allow_remote_execution: bool = False,
    allow_paid_execution: bool = False,
    now: str,
) -> dict[str, object]:
    """Issue a secret-free backend dispatch projection after Captain authorization.

    The caller must source installed/enabled/ready from canonical Captain Settings.
    This function deliberately does not accept provider credentials, model IDs, prompts,
    repository paths, or mutable backend configuration.
    """
    backend_id, descriptor = _backend(backend_id)
    installed = _bool(installed, "installed")
    enabled = _bool(enabled, "enabled")
    ready = _bool(ready, "ready")
    allow_optional_backend = _bool(allow_optional_backend, "allow_optional_backend")
    allow_remote_execution = _bool(allow_remote_execution, "allow_remote_execution")
    allow_paid_execution = _bool(allow_paid_execution, "allow_paid_execution")

    if not installed or not enabled or not ready:
        raise PermissionError("builder backend is not ready in Captain Settings")
    if bool(descriptor["optional"]) and not allow_optional_backend:
        raise PermissionError("optional builder backend requires explicit Captain selection")
    if execution_mode not in {"local", "remote-free", "remote-paid"}:
        raise ValueError("invalid execution_mode")
    if execution_mode != "local":
        if not bool(descriptor["remote_capable"]):
            raise PermissionError("builder backend does not permit remote execution")
        if not allow_remote_execution:
            raise PermissionError("remote builder execution requires explicit approval")
    if execution_mode == "remote-paid" and not allow_paid_execution:
        raise PermissionError("paid builder execution requires explicit approval")

    authorized = authorize_builder_action(
        session,
        chat_id=chat_id,
        project_id=project_id,
        repo_scope=repo_scope,
        session_id=session_id,
        repo_head=repo_head,
        worktree_digest=worktree_digest,
        state_epoch=state_epoch,
        capability=capability,
        now=now,
    )
    scope = parse_scope({"chat_id": chat_id, "project_id": project_id, "repo_scope": repo_scope})
    session_binding = _digest(authorized.get("binding_digest"), "session_binding")
    adapter_kind = str(descriptor["adapter_kind"])
    row = {
        "schema_version": SCHEMA_VERSION,
        "authority": _AUTHORITY,
        "scope": scope.as_dict(),
        "session_binding": session_binding,
        "state_epoch": state_epoch,
        "backend_id": backend_id,
        "adapter_kind": adapter_kind,
        "capability": capability,
        "execution_mode": execution_mode,
    }
    row["binding_digest"] = _binding(
        scope,
        session_binding=session_binding,
        state_epoch=state_epoch,
        backend_id=backend_id,
        adapter_kind=adapter_kind,
        capability=capability,
        execution_mode=execution_mode,
    )
    return row


def validate_builder_backend_dispatch(
    dispatch: Mapping[str, object],
    session: Mapping[str, object],
    *,
    chat_id: str,
    project_id: str,
    repo_scope: str,
    session_id: str,
    repo_head: str,
    worktree_digest: str,
    state_epoch: int,
    capability: str,
    now: str,
) -> dict[str, object]:
    required = {
        "schema_version", "authority", "scope", "session_binding", "state_epoch",
        "backend_id", "adapter_kind", "capability", "execution_mode", "binding_digest",
    }
    if not isinstance(dispatch, Mapping) or set(dispatch) != required:
        raise ValueError("invalid builder backend dispatch schema")
    if dispatch.get("schema_version") != SCHEMA_VERSION or dispatch.get("authority") != _AUTHORITY:
        raise ValueError("invalid builder backend dispatch authority")

    backend_id, descriptor = _backend(dispatch.get("backend_id"))
    if dispatch.get("adapter_kind") != descriptor["adapter_kind"]:
        raise ValueError("builder backend adapter changed")
    if dispatch.get("capability") != capability:
        raise PermissionError("builder backend capability mismatch")
    if dispatch.get("state_epoch") != state_epoch:
        raise PermissionError("builder backend state epoch changed")
    execution_mode = dispatch.get("execution_mode")
    if execution_mode not in {"local", "remote-free", "remote-paid"}:
        raise ValueError("invalid execution_mode")

    authorized = authorize_builder_action(
        session,
        chat_id=chat_id,
        project_id=project_id,
        repo_scope=repo_scope,
        session_id=session_id,
        repo_head=repo_head,
        worktree_digest=worktree_digest,
        state_epoch=state_epoch,
        capability=capability,
        now=now,
    )
    scope = parse_scope(dispatch.get("scope"))
    expected_scope = parse_scope({"chat_id": chat_id, "project_id": project_id, "repo_scope": repo_scope})
    if scope != expected_scope:
        raise PermissionError("builder backend scope mismatch")
    session_binding = _digest(dispatch.get("session_binding"), "session_binding")
    expected_session_binding = _digest(authorized.get("binding_digest"), "session_binding")
    if not hmac.compare_digest(session_binding, expected_session_binding):
        raise PermissionError("builder backend session changed")
    digest = _digest(dispatch.get("binding_digest"), "binding_digest")
    expected_digest = _binding(
        scope,
        session_binding=session_binding,
        state_epoch=state_epoch,
        backend_id=backend_id,
        adapter_kind=str(descriptor["adapter_kind"]),
        capability=capability,
        execution_mode=str(execution_mode),
    )
    if not hmac.compare_digest(digest, expected_digest):
        raise ValueError("builder backend dispatch was modified")
    return dict(dispatch)
