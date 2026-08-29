"""Fail-closed scope contract for Captain background/builder jobs."""
from __future__ import annotations
from dataclasses import dataclass
import hashlib
import re

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_ALLOWED_KINDS = {"research", "build", "test", "review", "debug", "connector"}

class ScopeError(ValueError):
    pass

@dataclass(frozen=True)
class JobScope:
    chat_id: str
    project_id: str
    repo_scope_hash: str


def _valid_id(value: object, label: str) -> str:
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise ScopeError(f"invalid {label}")
    return value


def make_scope(chat_id: object, project_id: object, repo_scope: object) -> JobScope:
    chat = _valid_id(chat_id, "chat_id")
    project = _valid_id(project_id, "project_id")
    if not isinstance(repo_scope, str) or not repo_scope.strip() or len(repo_scope) > 4096:
        raise ScopeError("invalid repo_scope")
    digest = hashlib.sha256(repo_scope.strip().encode("utf-8")).hexdigest()
    return JobScope(chat, project, digest)


def validate_job(payload: object, active: JobScope) -> dict:
    if not isinstance(payload, dict):
        raise ScopeError("job must be an object")
    kind = payload.get("kind")
    if kind not in _ALLOWED_KINDS:
        raise ScopeError("unknown job kind")
    job_id = _valid_id(payload.get("job_id"), "job_id")
    scope = make_scope(payload.get("chat_id"), payload.get("project_id"), payload.get("repo_scope"))
    if scope != active:
        raise ScopeError("cross-scope job rejected")
    return {"job_id": job_id, "kind": kind, "scope": scope}


def validate_result(job: dict, result: object, active: JobScope) -> dict:
    if job.get("scope") != active:
        raise ScopeError("inactive job scope")
    if not isinstance(result, dict):
        raise ScopeError("result must be an object")
    if result.get("job_id") != job.get("job_id"):
        raise ScopeError("result/job mismatch")
    # Never trust result-supplied scope; bind output to the validated job scope.
    return {"job_id": job["job_id"], "kind": job["kind"], "scope": active, "status": result.get("status", "unknown")}
