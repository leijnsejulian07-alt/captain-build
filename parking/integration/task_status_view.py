from __future__ import annotations

import re
from typing import Mapping, Sequence


SCHEMA_VERSION = 1
_TASK_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,191}$")
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_REPO_SCOPE_RE = re.compile(r"^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+(?:#[A-Za-z0-9._/@:-]{1,160})?$")
_ALLOWED_STATUS = {"queued", "running", "blocked", "succeeded", "failed", "cancelled"}
_ALLOWED_KIND = {"research", "build", "test", "review", "debug", "connector", "generic"}
MAX_EPOCH = 2**63 - 1
MAX_UPDATED_MS = 2**63 - 1


class TaskStatusError(ValueError):
    pass


def _id(name: str, value: object) -> str:
    if not isinstance(value, str) or not _ID_RE.fullmatch(value):
        raise TaskStatusError(f"invalid {name}")
    return value


def _task_id(value: object) -> str:
    if not isinstance(value, str) or not _TASK_ID_RE.fullmatch(value):
        raise TaskStatusError("invalid task_id")
    return value


def _repo_scope(value: object) -> str:
    if not isinstance(value, str) or len(value) > 256 or not _REPO_SCOPE_RE.fullmatch(value):
        raise TaskStatusError("invalid repo_scope")
    if ".." in value or value.startswith("/") or chr(92) in value:
        raise TaskStatusError("unsafe repo_scope")
    return value


def _epoch(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1 or value > MAX_EPOCH:
        raise TaskStatusError("invalid state_epoch")
    return value


def _updated_ms(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0 or value > MAX_UPDATED_MS:
        raise TaskStatusError("invalid updated_at_ms")
    return value


def _progress(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0 or value > 100:
        raise TaskStatusError("invalid progress_percent")
    return value


def _parse_job(job: Mapping[str, object]) -> dict[str, object]:
    required = {
        "schema_version", "task_id", "chat_id", "project_id", "repo_scope",
        "state_epoch", "status", "kind", "progress_percent", "updated_at_ms",
    }
    if not isinstance(job, Mapping) or set(job) != required or job.get("schema_version") != SCHEMA_VERSION:
        raise TaskStatusError("invalid task status record")

    task_id = _task_id(job.get("task_id"))
    chat_id = _id("chat_id", job.get("chat_id"))
    status = job.get("status")
    kind = job.get("kind")
    if status not in _ALLOWED_STATUS:
        raise TaskStatusError("invalid task status")
    if kind not in _ALLOWED_KIND:
        raise TaskStatusError("invalid task kind")

    project_id = job.get("project_id")
    repo_scope = job.get("repo_scope")
    state_epoch = job.get("state_epoch")
    project_bound = project_id is not None or repo_scope is not None or state_epoch is not None
    if project_bound:
        if project_id is None or repo_scope is None or state_epoch is None:
            raise TaskStatusError("project task scope must be complete")
        parsed_project = _id("project_id", project_id)
        parsed_repo = _repo_scope(repo_scope)
        parsed_epoch = _epoch(state_epoch)
    else:
        parsed_project = None
        parsed_repo = None
        parsed_epoch = None

    return {
        "task_id": task_id,
        "chat_id": chat_id,
        "project_id": parsed_project,
        "repo_scope": parsed_repo,
        "state_epoch": parsed_epoch,
        "status": status,
        "kind": kind,
        "progress_percent": _progress(job.get("progress_percent")),
        "updated_at_ms": _updated_ms(job.get("updated_at_ms")),
    }


def build_task_status_projection(
    jobs: Sequence[Mapping[str, object]],
    *,
    chat_id: str,
    project_id: str | None = None,
    repo_scope: str | None = None,
    state_epoch: int | None = None,
) -> dict[str, object]:
    """Return the only task records safe for the active Captain surface.

    Project surfaces require the full project/repository/epoch tuple and hide both
    cross-scope and stale-epoch work. Normal chat accepts only explicitly
    non-project jobs for the exact chat. Cross-chat records are never counted or
    surfaced, avoiding metadata leaks across conversations.
    """
    active_chat = _id("chat_id", chat_id)
    project_mode = project_id is not None or repo_scope is not None or state_epoch is not None
    if project_mode:
        if project_id is None or repo_scope is None or state_epoch is None:
            raise TaskStatusError("active project scope must be complete")
        active_project = _id("project_id", project_id)
        active_repo = _repo_scope(repo_scope)
        active_epoch = _epoch(state_epoch)
    else:
        active_project = None
        active_repo = None
        active_epoch = None

    parsed = [_parse_job(job) for job in jobs]
    task_ids = [job["task_id"] for job in parsed]
    if len(set(task_ids)) != len(task_ids):
        raise TaskStatusError("duplicate task_id")

    visible: list[dict[str, object]] = []
    stale_hidden_count = 0
    for job in parsed:
        if job["chat_id"] != active_chat:
            continue
        if not project_mode:
            if job["project_id"] is None:
                visible.append(job)
            continue
        if job["project_id"] != active_project or job["repo_scope"] != active_repo:
            continue
        if job["state_epoch"] != active_epoch:
            stale_hidden_count += 1
            continue
        visible.append(job)

    visible.sort(key=lambda item: (-int(item["updated_at_ms"]), str(item["task_id"])))
    running_count = sum(item["status"] in {"queued", "running", "blocked"} for item in visible)
    attention_count = sum(item["status"] in {"blocked", "failed"} for item in visible)

    safe_jobs = [
        {
            "task_id": item["task_id"],
            "status": item["status"],
            "kind": item["kind"],
            "progress_percent": item["progress_percent"],
            "updated_at_ms": item["updated_at_ms"],
        }
        for item in visible
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "mode": "project" if project_mode else "chat",
        "jobs": safe_jobs,
        "running_count": running_count,
        "attention_count": attention_count,
        "stale_hidden_count": stale_hidden_count,
        "secret_fields": [],
    }
