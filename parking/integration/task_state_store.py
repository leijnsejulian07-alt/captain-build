from __future__ import annotations

import hashlib
import hmac
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


SCHEMA_VERSION = 1
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_TASK_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,191}$")
_REPO_RE = re.compile(r"^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+(?:#[A-Za-z0-9._/@:-]{1,160})?$")
_KINDS = {"research", "build", "test", "review", "debug", "connector", "generic"}
_STATUSES = {"queued", "running", "blocked", "succeeded", "failed", "cancelled"}
_TERMINAL = {"succeeded", "failed", "cancelled"}
_TRANSITIONS = {
    "queued": {"running", "blocked", "succeeded", "failed", "cancelled"},
    "running": {"blocked", "succeeded", "failed", "cancelled"},
    "blocked": {"running", "failed", "cancelled"},
    "succeeded": set(),
    "failed": set(),
    "cancelled": set(),
}
_MAX_I64 = 2**63 - 1


class TaskStateError(ValueError):
    pass


@dataclass(frozen=True)
class TaskScope:
    chat_id: str
    project_id: str | None = None
    repo_scope: str | None = None
    state_epoch: int | None = None

    def __post_init__(self) -> None:
        _valid_id("chat_id", self.chat_id)
        project_mode = self.project_id is not None or self.repo_scope is not None or self.state_epoch is not None
        if not project_mode:
            return
        if self.project_id is None or self.repo_scope is None or self.state_epoch is None:
            raise TaskStateError("project task scope must be complete")
        _valid_id("project_id", self.project_id)
        _valid_repo(self.repo_scope)
        _valid_epoch(self.state_epoch)

    @property
    def mode(self) -> str:
        return "project" if self.project_id is not None else "chat"


def _valid_id(name: str, value: object) -> str:
    if not isinstance(value, str) or not _ID_RE.fullmatch(value):
        raise TaskStateError(f"invalid {name}")
    return value


def _valid_task_id(value: object) -> str:
    if not isinstance(value, str) or not _TASK_ID_RE.fullmatch(value):
        raise TaskStateError("invalid task_id")
    return value


def _valid_repo(value: object) -> str:
    if not isinstance(value, str) or len(value) > 256 or not _REPO_RE.fullmatch(value):
        raise TaskStateError("invalid repo_scope")
    if ".." in value or value.startswith("/") or "\\" in value:
        raise TaskStateError("unsafe repo_scope")
    return value


def _valid_epoch(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1 or value > _MAX_I64:
        raise TaskStateError("invalid state_epoch")
    return value


def _valid_ms(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0 or value > _MAX_I64:
        raise TaskStateError("invalid timestamp")
    return value


def _valid_progress(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 100:
        raise TaskStateError("invalid progress_percent")
    return value


def _scope_bytes(scope: TaskScope) -> bytes:
    parts = ["captain-task-scope-v1", scope.mode, scope.chat_id]
    if scope.mode == "project":
        parts.extend([str(scope.project_id), str(scope.repo_scope), str(scope.state_epoch)])
    return "\x1f".join(parts).encode("utf-8")


class TaskStateStore:
    """SQLite-backed task state; execution authority remains with Captain.

    Raw chat/project/repository identifiers are never persisted. Callers must
    present the exact current scope to recover records, so an epoch change makes
    old project records unreachable through the normal API. Persisted `running`
    work is never silently resumed after a process restart; `recover_after_restart`
    fences it to `blocked` and bumps its generation before Captain may reclaim it.
    """

    def __init__(self, path: str | Path, *, scope_key: bytes) -> None:
        if not isinstance(scope_key, bytes) or len(scope_key) < 32:
            raise TaskStateError("scope_key must be at least 32 bytes")
        self._scope_key = bytes(scope_key)
        self._db = sqlite3.connect(str(path), timeout=5.0, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA busy_timeout=5000")
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA synchronous=NORMAL")
        self._db.execute(
            """CREATE TABLE IF NOT EXISTS task_state (
                task_key TEXT PRIMARY KEY,
                scope_digest TEXT NOT NULL,
                task_id TEXT NOT NULL,
                kind TEXT NOT NULL,
                status TEXT NOT NULL,
                progress_percent INTEGER NOT NULL,
                updated_at_ms INTEGER NOT NULL,
                generation INTEGER NOT NULL CHECK(generation >= 1),
                schema_version INTEGER NOT NULL
            )"""
        )
        self._db.execute(
            "CREATE INDEX IF NOT EXISTS idx_task_state_scope ON task_state(scope_digest, updated_at_ms DESC)"
        )

    def close(self) -> None:
        self._db.close()

    def __enter__(self) -> "TaskStateStore":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _scope_digest(self, scope: TaskScope) -> str:
        return hmac.new(self._scope_key, _scope_bytes(scope), hashlib.sha256).hexdigest()

    def _task_key(self, scope_digest: str, task_id: str) -> str:
        material = f"captain-task-key-v1\x1f{scope_digest}\x1f{task_id}".encode()
        return hmac.new(self._scope_key, material, hashlib.sha256).hexdigest()

    def create_task(
        self, scope: TaskScope, *, task_id: str, kind: str, status: str = "queued",
        progress_percent: int = 0, updated_at_ms: int,
    ) -> dict[str, object]:
        task_id = _valid_task_id(task_id)
        if kind not in _KINDS:
            raise TaskStateError("invalid task kind")
        if status not in _STATUSES:
            raise TaskStateError("invalid task status")
        progress = _valid_progress(progress_percent)
        updated = _valid_ms(updated_at_ms)
        if status == "succeeded" and progress != 100:
            raise TaskStateError("succeeded task must be 100 percent")
        scope_digest = self._scope_digest(scope)
        task_key = self._task_key(scope_digest, task_id)
        try:
            self._db.execute(
                "INSERT INTO task_state VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?)",
                (task_key, scope_digest, task_id, kind, status, progress, updated, SCHEMA_VERSION),
            )
        except sqlite3.IntegrityError as exc:
            raise TaskStateError("task already exists in scope") from exc
        return self.get_task(scope, task_id=task_id)

    def get_task(self, scope: TaskScope, *, task_id: str) -> dict[str, object]:
        task_id = _valid_task_id(task_id)
        scope_digest = self._scope_digest(scope)
        row = self._db.execute(
            "SELECT * FROM task_state WHERE task_key=? AND scope_digest=?",
            (self._task_key(scope_digest, task_id), scope_digest),
        ).fetchone()
        if row is None or row["schema_version"] != SCHEMA_VERSION:
            raise TaskStateError("task not found in current scope")
        return self._record(scope, row)

    def list_tasks(self, scope: TaskScope) -> list[dict[str, object]]:
        scope_digest = self._scope_digest(scope)
        rows = self._db.execute(
            "SELECT * FROM task_state WHERE scope_digest=? ORDER BY updated_at_ms DESC, task_id ASC",
            (scope_digest,),
        ).fetchall()
        if any(row["schema_version"] != SCHEMA_VERSION for row in rows):
            raise TaskStateError("unsupported persisted task schema")
        return [self._record(scope, row) for row in rows]

    def transition(
        self, scope: TaskScope, *, task_id: str, expected_generation: int,
        status: str, progress_percent: int, updated_at_ms: int,
    ) -> dict[str, object]:
        task_id = _valid_task_id(task_id)
        if isinstance(expected_generation, bool) or not isinstance(expected_generation, int) or expected_generation < 1:
            raise TaskStateError("invalid expected_generation")
        if status not in _STATUSES:
            raise TaskStateError("invalid task status")
        progress = _valid_progress(progress_percent)
        updated = _valid_ms(updated_at_ms)
        if status == "succeeded" and progress != 100:
            raise TaskStateError("succeeded task must be 100 percent")

        scope_digest = self._scope_digest(scope)
        task_key = self._task_key(scope_digest, task_id)
        self._db.execute("BEGIN IMMEDIATE")
        try:
            row = self._db.execute(
                "SELECT * FROM task_state WHERE task_key=? AND scope_digest=?",
                (task_key, scope_digest),
            ).fetchone()
            if row is None or row["schema_version"] != SCHEMA_VERSION:
                raise TaskStateError("task not found in current scope")
            if row["generation"] != expected_generation:
                raise TaskStateError("stale task generation")
            if status == row["status"]:
                raise TaskStateError("task transition must change status")
            if status not in _TRANSITIONS[row["status"]]:
                raise TaskStateError("invalid task transition")
            if updated < row["updated_at_ms"]:
                raise TaskStateError("task timestamp regression")
            if progress < row["progress_percent"]:
                raise TaskStateError("task progress regression")
            next_generation = expected_generation + 1
            self._db.execute(
                "UPDATE task_state SET status=?, progress_percent=?, updated_at_ms=?, generation=? WHERE task_key=?",
                (status, progress, updated, next_generation, task_key),
            )
            self._db.execute("COMMIT")
        except Exception:
            self._db.execute("ROLLBACK")
            raise
        return self.get_task(scope, task_id=task_id)

    def recover_after_restart(self, scope: TaskScope, *, now_ms: int) -> list[dict[str, object]]:
        """Fence persisted running work; never auto-resume side effects after restart."""
        now = _valid_ms(now_ms)
        scope_digest = self._scope_digest(scope)
        self._db.execute("BEGIN IMMEDIATE")
        try:
            rows = self._db.execute(
                "SELECT task_key, updated_at_ms FROM task_state WHERE scope_digest=? AND status='running'",
                (scope_digest,),
            ).fetchall()
            for row in rows:
                self._db.execute(
                    "UPDATE task_state SET status='blocked', updated_at_ms=?, generation=generation+1 WHERE task_key=?",
                    (max(now, int(row["updated_at_ms"])), row["task_key"]),
                )
            self._db.execute("COMMIT")
        except Exception:
            self._db.execute("ROLLBACK")
            raise
        return self.list_tasks(scope)

    @staticmethod
    def _record(scope: TaskScope, row: sqlite3.Row) -> dict[str, object]:
        return {
            "schema_version": SCHEMA_VERSION,
            "task_id": row["task_id"],
            "chat_id": scope.chat_id,
            "project_id": scope.project_id,
            "repo_scope": scope.repo_scope,
            "state_epoch": scope.state_epoch,
            "status": row["status"],
            "kind": row["kind"],
            "progress_percent": row["progress_percent"],
            "updated_at_ms": row["updated_at_ms"],
            "generation": row["generation"],
        }
