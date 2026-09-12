import pytest

from scoped_job_view import (
    JobRecord,
    JobStatus,
    ProjectScope,
    ScopeError,
    may_cancel,
    may_retry,
    project_job_view,
)


def scope(epoch=7, chat="chat-a", project="project-a", repo="repo-a"):
    return ProjectScope(chat, project, repo, epoch)


def job(status=JobStatus.RUNNING, epoch=7, task="task-a", retryable=False):
    return JobRecord(
        job_id="job-a",
        owner_task_id=task,
        scope=scope(epoch=epoch),
        status=status,
        progress_percent=42,
        phase="testing",
        summary="Running regression suite",
        retryable=retryable,
    )


def test_current_job_projects_minimal_ui_state():
    view = project_job_view([job()], scope(), {"task-a"})
    assert view == [{
        "job_id": "job-a",
        "status": "running",
        "progress_percent": 42,
        "phase": "testing",
        "summary": "Running regression suite",
        "retryable": False,
    }]
    assert "project_id" not in view[0]
    assert "repo_scope" not in view[0]
    assert "owner_task_id" not in view[0]


@pytest.mark.parametrize("wrong", [
    scope(epoch=8),
    scope(chat="chat-b"),
    scope(project="project-b"),
    scope(repo="repo-b"),
])
def test_stale_or_cross_scope_job_fails_closed(wrong):
    with pytest.raises(ScopeError):
        project_job_view([job()], wrong, {"task-a"})


def test_task_ownership_mismatch_fails_closed():
    with pytest.raises(ScopeError):
        project_job_view([job()], scope(), {"task-b"})


def test_retry_and_cancel_are_scope_bound_and_status_bound():
    failed = job(status=JobStatus.FAILED, retryable=True)
    running = job(status=JobStatus.RUNNING)
    assert may_retry(failed, scope(), "task-a") is True
    assert may_cancel(failed, scope(), "task-a") is False
    assert may_retry(running, scope(), "task-a") is False
    assert may_cancel(running, scope(), "task-a") is True


def test_stale_epoch_cannot_retry_or_cancel():
    with pytest.raises(ScopeError):
        may_retry(job(status=JobStatus.FAILED, retryable=True), scope(epoch=8), "task-a")
    with pytest.raises(ScopeError):
        may_cancel(job(), scope(epoch=8), "task-a")


@pytest.mark.parametrize("field,value", [
    ("progress_percent", 101),
    ("phase", "bad\nphase"),
    ("summary", "bad\nsummary"),
])
def test_invalid_ui_payload_is_rejected(field, value):
    kwargs = dict(
        job_id="job-a",
        owner_task_id="task-a",
        scope=scope(),
        status=JobStatus.RUNNING,
        progress_percent=42,
        phase="testing",
        summary="ok",
    )
    kwargs[field] = value
    with pytest.raises(ScopeError):
        project_job_view([JobRecord(**kwargs)], scope(), {"task-a"})
