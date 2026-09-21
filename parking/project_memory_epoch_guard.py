"""Fail-closed Project Memory/context scope guard for Captain parking integration.

Dependency-free reference implementation. Captain remains the authority for the
current Project State epoch; persisted envelopes never grant authority themselves.
Normal non-project chat bypasses project memory rather than inheriting a project.
"""
from dataclasses import dataclass
from typing import Any, Mapping, Optional


class ScopeDenied(PermissionError):
    pass


@dataclass(frozen=True)
class ActiveScope:
    chat_id: str
    project_id: str
    state_epoch: int
    repo_scope: Optional[str] = None


def _nonempty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def authorize_project_envelope(envelope: Mapping[str, Any], active: ActiveScope) -> Mapping[str, Any]:
    """Return payload only when the persisted envelope exactly matches active scope.

    Fails closed for malformed/stale/cross-project data. repo_scope is enforced when
    either side has one, preventing repo-bound context from becoming project-global.
    """
    if not isinstance(envelope, Mapping) or envelope.get("version") != 1:
        raise ScopeDenied("invalid memory envelope")
    if envelope.get("kind") not in {"project_memory", "project_context"}:
        raise ScopeDenied("invalid memory kind")
    scope = envelope.get("scope")
    if not isinstance(scope, Mapping):
        raise ScopeDenied("missing memory scope")
    if not (_nonempty(active.chat_id) and _nonempty(active.project_id)) or not isinstance(active.state_epoch, int) or active.state_epoch < 0:
        raise ScopeDenied("invalid active Project State")
    if scope.get("chat_id") != active.chat_id or scope.get("project_id") != active.project_id:
        raise ScopeDenied("cross-scope memory denied")
    if scope.get("state_epoch") != active.state_epoch:
        raise ScopeDenied("stale Project State epoch")
    stored_repo = scope.get("repo_scope")
    if stored_repo is not None or active.repo_scope is not None:
        if stored_repo != active.repo_scope:
            raise ScopeDenied("repo scope mismatch")
    payload = envelope.get("payload")
    if not isinstance(payload, Mapping):
        raise ScopeDenied("invalid memory payload")
    return payload


def project_memory_for_chat(envelope: Optional[Mapping[str, Any]], active: Optional[ActiveScope]) -> Optional[Mapping[str, Any]]:
    """Safe read path: ordinary non-project chat receives no project memory."""
    if active is None:
        return None
    if envelope is None:
        return None
    return authorize_project_envelope(envelope, active)
