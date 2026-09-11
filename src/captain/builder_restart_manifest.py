"""Secret-free restart manifest for a context-bound Captain builder session.

This module does not resume work by itself. It binds the independently persisted
builder phase/job checkpoints to the exact Captain context that opened the
session. After restart Captain must reassemble current memory/context through the
canonical RequestContextGateway and prove the digest still matches before any
session/job rehydration is considered.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping, Tuple

from .builder_job_recovery import EpochBoundBuilderJobStore
from .builder_phase_machine import BuilderPhaseStateMachine
from .project_authority import AuthorityError, ProjectAuthority, require_current_epoch
from .request_context_gateway import BuilderContextEnvelope, RequestContextGateway


def _plain(value: object, *, path: str = "$") -> object:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            raise AuthorityError(f"non-finite restart context value at {path}")
        return value
    if type(value) is dict or isinstance(value, MappingProxyType):
        out = {}
        for key in sorted(value):
            if not isinstance(key, str) or not key:
                raise AuthorityError(f"invalid restart context key at {path}")
            out[key] = _plain(value[key], path=f"{path}.{key}")
        return out
    if type(value) is tuple:
        return [_plain(item, path=f"{path}[{index}]") for index, item in enumerate(value)]
    raise AuthorityError(f"unsupported restart context value at {path}: {type(value).__name__}")


def context_digest(context: BuilderContextEnvelope) -> str:
    """Return a deterministic digest without persisting prompt/memory contents."""
    if type(context) is not BuilderContextEnvelope:
        raise AuthorityError("restart manifest requires canonical builder context")
    context.authority.validate()
    require_current_epoch(context.authority, current_epoch=context.current_epoch)
    items = [
        {
            "record_id": item.record_id,
            "kind": item.kind,
            "provenance": item.provenance,
            "payload": _plain(item.payload),
        }
        for item in context.prompt_context.items
    ]
    payload = {
        "chat_id": context.authority.chat_id,
        "project_id": context.authority.project_id,
        "repo_scope": context.repo_scope,
        "state_epoch": context.current_epoch,
        "capabilities": list(context.capabilities),
        "items": items,
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class BuilderRestartManifest:
    session_id: str
    authority: ProjectAuthority
    capabilities: Tuple[str, ...]
    context_sha256: str
    phase_state: Mapping[str, object]
    jobs: Tuple[Mapping[str, object], ...]

    def safe_payload(self) -> dict:
        self.authority.validate()
        if self.authority.is_normal_chat:
            raise AuthorityError("restart manifest requires project authority")
        if not isinstance(self.session_id, str) or not self.session_id.strip():
            raise AuthorityError("restart manifest requires a non-empty session_id")
        if type(self.capabilities) is not tuple or not all(isinstance(x, str) for x in self.capabilities):
            raise AuthorityError("restart manifest capabilities must be strings")
        if len(self.context_sha256) != 64 or any(c not in "0123456789abcdef" for c in self.context_sha256):
            raise AuthorityError("restart manifest context digest is invalid")
        return {
            "version": 1,
            "session_id": self.session_id,
            "chat_id": self.authority.chat_id,
            "project_id": self.authority.project_id,
            "repo_scope": self.authority.repo_scope,
            "state_epoch": self.authority.state_epoch,
            "capabilities": list(self.capabilities),
            "context_sha256": self.context_sha256,
            "phase_state": dict(self.phase_state),
            "jobs": [dict(row) for row in self.jobs],
        }


def _validate_nested_checkpoints(
    record: Mapping[str, object], *, authority: ProjectAuthority, current_epoch: int
) -> None:
    phase_state = record["phase_state"]
    job_rows = record["jobs"]
    if type(phase_state) is not dict or type(job_rows) is not list:
        raise AuthorityError("restart manifest nested checkpoints are not canonical")
    session_id = record["session_id"]
    if not isinstance(session_id, str) or not session_id.strip():
        raise AuthorityError("restart manifest session_id is invalid")
    if phase_state.get("session_id") != session_id:
        raise AuthorityError("restart manifest phase checkpoint session mismatch")

    phase_validator = BuilderPhaseStateMachine()
    phase_validator.restore_state(
        phase_state, authority=authority, current_epoch=current_epoch
    )
    job_validator = EpochBoundBuilderJobStore()
    job_validator.restore_state(
        job_rows, request=authority, current_epoch=current_epoch
    )
    attempted = set(phase_state["attempted"])
    for row in job_rows:
        if row["session_id"] != session_id:
            raise AuthorityError("restart manifest job belongs to a different session")
        if row["status"] != "queued" and row["phase"] not in attempted:
            raise AuthorityError("durable builder job is inconsistent with phase checkpoint")


def export_restart_manifest(
    *,
    session_id: str,
    context: BuilderContextEnvelope,
    phases: BuilderPhaseStateMachine,
    jobs: EpochBoundBuilderJobStore,
    current_epoch: int,
) -> BuilderRestartManifest:
    """Describe one live context/session using secret-free sub-checkpoints."""
    if type(phases) is not BuilderPhaseStateMachine or type(jobs) is not EpochBoundBuilderJobStore:
        raise AuthorityError("restart manifest requires canonical Captain stores")
    authority = context.authority
    require_current_epoch(authority, current_epoch=current_epoch)
    if context.current_epoch != current_epoch:
        raise AuthorityError("restart context epoch is stale")
    phase_state = phases.export_state(
        authority=authority, session_id=session_id, current_epoch=current_epoch
    )
    rows = tuple(
        row for row in jobs.export_state(request=authority, current_epoch=current_epoch)
        if row["session_id"] == session_id
    )
    attempted = set(phase_state["attempted"])
    for row in rows:
        if row["status"] != "queued" and row["phase"] not in attempted:
            raise AuthorityError("durable builder job is inconsistent with phase checkpoint")
    return BuilderRestartManifest(
        session_id=session_id,
        authority=authority,
        capabilities=context.capabilities,
        context_sha256=context_digest(context),
        phase_state=phase_state,
        jobs=rows,
    )


def verify_restart_context(
    record: Mapping[str, object],
    *,
    gateway: RequestContextGateway,
    request: ProjectAuthority,
    current_epoch: int,
) -> BuilderContextEnvelope:
    """Reassemble context and fully validate a persisted restart manifest."""
    if type(gateway) is not RequestContextGateway:
        raise AuthorityError("restart verification requires canonical RequestContextGateway")
    if type(record) is not dict:
        raise AuthorityError("restart manifest must be a canonical dict")
    expected = {
        "version", "session_id", "chat_id", "project_id", "repo_scope", "state_epoch",
        "capabilities", "context_sha256", "phase_state", "jobs",
    }
    if set(record) != expected or record["version"] != 1:
        raise AuthorityError("restart manifest schema/version mismatch")
    restored = ProjectAuthority(
        chat_id=record["chat_id"], project_id=record["project_id"],
        repo_scope=record["repo_scope"], state_epoch=record["state_epoch"],
    )
    request.require_same_owner(restored)
    require_current_epoch(restored, current_epoch=current_epoch)
    capabilities = record["capabilities"]
    if type(capabilities) is not list or not all(isinstance(x, str) for x in capabilities):
        raise AuthorityError("restart manifest capabilities are invalid")
    if len(set(capabilities)) != len(capabilities):
        raise AuthorityError("restart manifest capabilities contain duplicates")
    digest = record["context_sha256"]
    if not isinstance(digest, str):
        raise AuthorityError("restart manifest context digest is invalid")
    _validate_nested_checkpoints(record, authority=request, current_epoch=current_epoch)
    context = gateway.for_builder(
        request=request, current_epoch=current_epoch, capabilities=tuple(capabilities)
    )
    if context_digest(context) != digest:
        raise AuthorityError("Captain context changed since builder checkpoint")
    return context
