from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import re

_ALLOWED_BACKENDS = {"docker-sbx", "local-test"}
_ALLOWED_WORKSPACE_MODES = {"clone", "direct-ro"}
_ALLOWED_NETWORK_MODES = {"deny", "allowlist"}
_ALLOWED_CREDENTIAL_MODES = {"proxy", "none"}
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


@dataclass(frozen=True)
class SandboxLease:
    session_id: str
    chat_id: str
    project_id: str
    repo_scope: str
    state_epoch: int
    backend: str
    workspace_mode: str
    network_mode: str
    credential_mode: str
    scope_digest: str


def _require_id(name: str, value: str) -> str:
    value = (value or "").strip()
    if not _SAFE_ID.fullmatch(value):
        raise ValueError(f"invalid {name}")
    return value


def _require_scope(repo_scope: str) -> str:
    value = (repo_scope or "").strip()
    if not value or "\x00" in value:
        raise ValueError("invalid repo_scope")
    return value


def _scope_digest(chat_id: str, project_id: str, repo_scope: str, state_epoch: int) -> str:
    raw = f"{chat_id}\n{project_id}\n{repo_scope}\n{state_epoch}".encode("utf-8")
    return sha256(raw).hexdigest()


def create_sandbox_lease(
    *,
    session_id: str,
    chat_id: str,
    project_id: str,
    repo_scope: str,
    state_epoch: int,
    backend: str = "docker-sbx",
    workspace_mode: str = "clone",
    network_mode: str = "deny",
    credential_mode: str = "proxy",
) -> SandboxLease:
    session_id = _require_id("session_id", session_id)
    chat_id = _require_id("chat_id", chat_id)
    project_id = _require_id("project_id", project_id)
    repo_scope = _require_scope(repo_scope)
    if not isinstance(state_epoch, int) or state_epoch < 1:
        raise ValueError("state_epoch must be a positive integer")
    if backend not in _ALLOWED_BACKENDS:
        raise ValueError("unsupported sandbox backend")
    if workspace_mode not in _ALLOWED_WORKSPACE_MODES:
        raise ValueError("unsafe workspace mode")
    if network_mode not in _ALLOWED_NETWORK_MODES:
        raise ValueError("unsafe network mode")
    if credential_mode not in _ALLOWED_CREDENTIAL_MODES:
        raise ValueError("unsafe credential mode")

    return SandboxLease(
        session_id=session_id,
        chat_id=chat_id,
        project_id=project_id,
        repo_scope=repo_scope,
        state_epoch=state_epoch,
        backend=backend,
        workspace_mode=workspace_mode,
        network_mode=network_mode,
        credential_mode=credential_mode,
        scope_digest=_scope_digest(chat_id, project_id, repo_scope, state_epoch),
    )


def assert_sandbox_access(
    lease: SandboxLease,
    *,
    chat_id: str,
    project_id: str,
    repo_scope: str,
    state_epoch: int,
) -> None:
    expected = _scope_digest(
        _require_id("chat_id", chat_id),
        _require_id("project_id", project_id),
        _require_scope(repo_scope),
        state_epoch,
    )
    if state_epoch != lease.state_epoch or expected != lease.scope_digest:
        raise PermissionError("sandbox scope/epoch mismatch")


def validate_launch_capabilities(
    lease: SandboxLease,
    *,
    requested_network_hosts: tuple[str, ...] = (),
    raw_secret_values_present: bool = False,
) -> None:
    if raw_secret_values_present:
        raise PermissionError("raw secrets may not cross the sandbox boundary")
    if lease.credential_mode == "none" and raw_secret_values_present:
        raise PermissionError("credentials disabled for sandbox")
    if lease.network_mode == "deny" and requested_network_hosts:
        raise PermissionError("network denied by sandbox lease")
    if lease.network_mode == "allowlist":
        for host in requested_network_hosts:
            if not host or "/" in host or "://" in host or "@" in host:
                raise ValueError("invalid network allowlist host")
