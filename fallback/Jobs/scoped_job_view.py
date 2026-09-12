from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable


class ScopeError(ValueError):
    pass


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class ProjectScope:
    chat_id: str
    project_id: str
    repo_scope: str
    state_epoch: int

    def validate(self) -> None:
        if not self.chat_id or not self.project_id or not self.repo_scope:
            raise ScopeError("project job scope must be complete")
        if self.state_epoch < 0:
            raise ScopeError("state_epoch must be non-negative")


@dataclass(frozen=True)
class JobRecord:
    job_id: str
    owner_task_id: str
    scope: ProjectScope
    status: JobStatus
    progress_percent: int
    phase: str
    summary: str
    retryable: bool = False

    def validate(self) -> None:
        self.scope.validate()
        if not self.job_id or not self.owner_task_id:
            raise ScopeError("job ownership identifiers are required")
        if not 0 <= self.progress_percent <= 100:
            raise ScopeError("progress_percent must be between 0 and 100")
        if "\n" in self.phase or len(self.phase) > 80:
            raise ScopeError("phase must be a short single-line label")
        if "\n" in self.summary or len(self.summary) > 240:
            raise ScopeError("summary must be short and single-line")


def authorize_job_view(record: JobRecord, current_scope: ProjectScope, owner_task_id: str) -> JobRecord:
    record.validate()
    current_scope.validate()
    if record.scope != current_scope:
        raise ScopeError("job is not accessible in the current Project State epoch")
    if record.owner_task_id != owner_task_id:
        raise ScopeError("job/task ownership mismatch")
    return record


def project_job_view(records: Iterable[JobRecord], current_scope: ProjectScope, owner_task_ids: set[str]) -> list[dict[str, object]]:
    """Return a secret-minimized UI projection for only currently-authorized jobs.

    Caller-provided records from stale/cross-project scopes fail closed instead of being
    silently filtered, so backend scope bugs cannot become invisible UI leaks.
    """
    current_scope.validate()
    result: list[dict[str, object]] = []
    for record in records:
        authorize_job_view(record, current_scope, record.owner_task_id)
        if record.owner_task_id not in owner_task_ids:
            raise ScopeError("job belongs to a task outside the authorized task set")
        result.append(
            {
                "job_id": record.job_id,
                "status": record.status.value,
                "progress_percent": record.progress_percent,
                "phase": record.phase,
                "summary": record.summary,
                "retryable": record.retryable,
            }
        )
    return result


def may_retry(record: JobRecord, current_scope: ProjectScope, owner_task_id: str) -> bool:
    authorize_job_view(record, current_scope, owner_task_id)
    return record.retryable and record.status in {JobStatus.FAILED, JobStatus.BLOCKED}


def may_cancel(record: JobRecord, current_scope: ProjectScope, owner_task_id: str) -> bool:
    authorize_job_view(record, current_scope, owner_task_id)
    return record.status in {JobStatus.QUEUED, JobStatus.RUNNING, JobStatus.BLOCKED}
