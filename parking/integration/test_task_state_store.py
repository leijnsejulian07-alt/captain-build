from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from parking.integration.task_state_store import TaskScope, TaskStateError, TaskStateStore
from parking.integration.task_status_view import build_task_status_projection


KEY = b"captain-test-scope-key-32-bytes!!" + b"x" * 8


def status_record(record: dict[str, object]) -> dict[str, object]:
    allowed = {
        "schema_version", "task_id", "chat_id", "project_id", "repo_scope",
        "state_epoch", "status", "kind", "progress_percent", "updated_at_ms",
    }
    return {key: value for key, value in record.items() if key in allowed}


class TaskStateStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "tasks.sqlite3"
        self.scope = TaskScope("chat-a", "project-a", "owner/repo#main", 7)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def open(self) -> TaskStateStore:
        return TaskStateStore(self.db, scope_key=KEY)

    def test_restart_fences_running_job_and_bumps_generation(self) -> None:
        with self.open() as store:
            created = store.create_task(
                self.scope, task_id="build-1", kind="build", status="running",
                progress_percent=40, updated_at_ms=100,
            )
            self.assertEqual(created["generation"], 1)
        with self.open() as store:
            recovered = store.recover_after_restart(self.scope, now_ms=200)
            self.assertEqual(len(recovered), 1)
            self.assertEqual(recovered[0]["status"], "blocked")
            self.assertEqual(recovered[0]["generation"], 2)
            self.assertEqual(recovered[0]["progress_percent"], 40)

    def test_restart_does_not_rewrite_terminal_job(self) -> None:
        with self.open() as store:
            store.create_task(
                self.scope, task_id="done-1", kind="test", status="succeeded",
                progress_percent=100, updated_at_ms=100,
            )
        with self.open() as store:
            rows = store.recover_after_restart(self.scope, now_ms=300)
            self.assertEqual(rows[0]["status"], "succeeded")
            self.assertEqual(rows[0]["generation"], 1)
            self.assertEqual(rows[0]["updated_at_ms"], 100)

    def test_stale_epoch_is_inaccessible(self) -> None:
        with self.open() as store:
            store.create_task(
                self.scope, task_id="research-1", kind="research", updated_at_ms=10,
            )
            newer = TaskScope("chat-a", "project-a", "owner/repo#main", 8)
            self.assertEqual(store.list_tasks(newer), [])
            with self.assertRaises(TaskStateError):
                store.get_task(newer, task_id="research-1")

    def test_cross_project_repo_and_chat_are_inaccessible(self) -> None:
        with self.open() as store:
            store.create_task(self.scope, task_id="t1", kind="generic", updated_at_ms=10)
            wrong_scopes = [
                TaskScope("chat-b", "project-a", "owner/repo#main", 7),
                TaskScope("chat-a", "project-b", "owner/repo#main", 7),
                TaskScope("chat-a", "project-a", "owner/other#main", 7),
            ]
            for scope in wrong_scopes:
                self.assertEqual(store.list_tasks(scope), [])
                with self.assertRaises(TaskStateError):
                    store.get_task(scope, task_id="t1")

    def test_non_project_chat_survives_restart_without_project_scope(self) -> None:
        chat = TaskScope("normal-chat")
        with self.open() as store:
            store.create_task(chat, task_id="q1", kind="generic", updated_at_ms=1)
        with self.open() as store:
            rows = store.list_tasks(chat)
            self.assertEqual(len(rows), 1)
            projected = build_task_status_projection(
                [status_record(row) for row in rows], chat_id="normal-chat"
            )
            self.assertEqual(projected["mode"], "chat")
            self.assertEqual(projected["jobs"][0]["task_id"], "q1")

    def test_durable_rows_feed_existing_project_status_projection(self) -> None:
        with self.open() as store:
            store.create_task(
                self.scope, task_id="test-1", kind="test", status="blocked",
                progress_percent=60, updated_at_ms=123,
            )
            rows = store.list_tasks(self.scope)
        projected = build_task_status_projection(
            [status_record(row) for row in rows],
            chat_id="chat-a", project_id="project-a", repo_scope="owner/repo#main", state_epoch=7,
        )
        self.assertEqual(projected["running_count"], 1)
        self.assertEqual(projected["attention_count"], 1)
        self.assertNotIn("generation", projected["jobs"][0])
        self.assertNotIn("repo_scope", projected["jobs"][0])

    def test_stale_generation_cannot_resume_after_restart(self) -> None:
        with self.open() as store:
            old = store.create_task(
                self.scope, task_id="build-2", kind="build", status="running",
                progress_percent=30, updated_at_ms=10,
            )
        with self.open() as store:
            store.recover_after_restart(self.scope, now_ms=20)
            with self.assertRaisesRegex(TaskStateError, "stale task generation"):
                store.transition(
                    self.scope, task_id="build-2", expected_generation=old["generation"],
                    status="running", progress_percent=30, updated_at_ms=30,
                )
            current = store.get_task(self.scope, task_id="build-2")
            resumed = store.transition(
                self.scope, task_id="build-2", expected_generation=current["generation"],
                status="running", progress_percent=30, updated_at_ms=30,
            )
            self.assertEqual(resumed["generation"], 3)

    def test_terminal_and_progress_regressions_fail_closed(self) -> None:
        with self.open() as store:
            row = store.create_task(
                self.scope, task_id="t2", kind="debug", status="running",
                progress_percent=80, updated_at_ms=100,
            )
            with self.assertRaisesRegex(TaskStateError, "progress regression"):
                store.transition(
                    self.scope, task_id="t2", expected_generation=row["generation"],
                    status="blocked", progress_percent=79, updated_at_ms=101,
                )
            failed = store.transition(
                self.scope, task_id="t2", expected_generation=row["generation"],
                status="failed", progress_percent=80, updated_at_ms=102,
            )
            with self.assertRaisesRegex(TaskStateError, "invalid task transition"):
                store.transition(
                    self.scope, task_id="t2", expected_generation=failed["generation"],
                    status="running", progress_percent=80, updated_at_ms=103,
                )

    def test_scope_identifiers_and_key_are_not_persisted(self) -> None:
        with self.open() as store:
            store.create_task(
                self.scope, task_id="opaque-task-1", kind="connector", updated_at_ms=55,
            )
            store._db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        raw = self.db.read_bytes()
        for forbidden in (b"chat-a", b"project-a", b"owner/repo#main", KEY):
            self.assertNotIn(forbidden, raw)

    def test_duplicate_same_task_in_same_scope_fails_but_other_scope_is_independent(self) -> None:
        with self.open() as store:
            store.create_task(self.scope, task_id="same", kind="generic", updated_at_ms=1)
            with self.assertRaisesRegex(TaskStateError, "already exists"):
                store.create_task(self.scope, task_id="same", kind="generic", updated_at_ms=2)
            other = TaskScope("chat-a", "project-a", "owner/repo#main", 8)
            store.create_task(other, task_id="same", kind="generic", updated_at_ms=2)
            self.assertEqual(len(store.list_tasks(other)), 1)


if __name__ == "__main__":
    unittest.main()
