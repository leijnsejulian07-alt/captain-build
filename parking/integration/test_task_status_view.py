from __future__ import annotations

import unittest

from task_status_view import TaskStatusError, build_task_status_projection


def job(task_id: str, **overrides):
    value = {
        "schema_version": 1,
        "task_id": task_id,
        "chat_id": "chat-a",
        "project_id": "project-a",
        "repo_scope": "owner/repo#main",
        "state_epoch": 7,
        "status": "running",
        "kind": "build",
        "progress_percent": 40,
        "updated_at_ms": 1000,
    }
    value.update(overrides)
    return value


class TaskStatusViewTests(unittest.TestCase):
    def test_project_surface_only_exposes_exact_scope_and_epoch(self):
        projection = build_task_status_projection(
            [
                job("visible"),
                job("old", state_epoch=6),
                job("other-project", project_id="project-b"),
                job("other-repo", repo_scope="owner/other#main"),
                job("other-chat", chat_id="chat-b"),
            ],
            chat_id="chat-a",
            project_id="project-a",
            repo_scope="owner/repo#main",
            state_epoch=7,
        )
        self.assertEqual([item["task_id"] for item in projection["jobs"]], ["visible"])
        self.assertEqual(projection["stale_hidden_count"], 1)
        self.assertEqual(projection["running_count"], 1)

    def test_cross_scope_jobs_do_not_affect_counts(self):
        projection = build_task_status_projection(
            [
                job("visible", status="succeeded", progress_percent=100),
                job("failed-other-project", project_id="project-b", status="failed"),
                job("blocked-other-chat", chat_id="chat-b", status="blocked"),
            ],
            chat_id="chat-a",
            project_id="project-a",
            repo_scope="owner/repo#main",
            state_epoch=7,
        )
        self.assertEqual(projection["attention_count"], 0)
        self.assertEqual(projection["running_count"], 0)

    def test_stale_epoch_is_hidden_but_counted_only_inside_same_scope(self):
        projection = build_task_status_projection(
            [
                job("stale-a", state_epoch=5),
                job("stale-b", state_epoch=6),
                job("foreign-stale", project_id="project-b", state_epoch=6),
            ],
            chat_id="chat-a",
            project_id="project-a",
            repo_scope="owner/repo#main",
            state_epoch=7,
        )
        self.assertEqual(projection["jobs"], [])
        self.assertEqual(projection["stale_hidden_count"], 2)

    def test_normal_chat_keeps_non_project_jobs_useful(self):
        projection = build_task_status_projection(
            [
                job("normal", project_id=None, repo_scope=None, state_epoch=None, kind="generic"),
                job("project-bound"),
            ],
            chat_id="chat-a",
        )
        self.assertEqual(projection["mode"], "chat")
        self.assertEqual([item["task_id"] for item in projection["jobs"]], ["normal"])
        self.assertEqual(projection["stale_hidden_count"], 0)

    def test_normal_chat_is_exact_chat_bound(self):
        projection = build_task_status_projection(
            [
                job("mine", project_id=None, repo_scope=None, state_epoch=None),
                job("foreign", chat_id="chat-b", project_id=None, repo_scope=None, state_epoch=None, status="failed"),
            ],
            chat_id="chat-a",
        )
        self.assertEqual([item["task_id"] for item in projection["jobs"]], ["mine"])
        self.assertEqual(projection["attention_count"], 0)

    def test_partial_project_scope_fails_closed(self):
        with self.assertRaises(TaskStatusError):
            build_task_status_projection([], chat_id="chat-a", project_id="project-a")

    def test_partial_job_scope_fails_closed(self):
        with self.assertRaises(TaskStatusError):
            build_task_status_projection(
                [job("bad", state_epoch=None)],
                chat_id="chat-a",
                project_id="project-a",
                repo_scope="owner/repo#main",
                state_epoch=7,
            )

    def test_duplicate_task_id_fails_closed(self):
        with self.assertRaises(TaskStatusError):
            build_task_status_projection(
                [job("same"), job("same", chat_id="chat-b")],
                chat_id="chat-a",
                project_id="project-a",
                repo_scope="owner/repo#main",
                state_epoch=7,
            )

    def test_projection_is_deterministic_and_scope_free(self):
        projection = build_task_status_projection(
            [
                job("b", updated_at_ms=2000),
                job("a", updated_at_ms=2000),
                job("c", updated_at_ms=3000, status="blocked"),
            ],
            chat_id="chat-a",
            project_id="project-a",
            repo_scope="owner/repo#main",
            state_epoch=7,
        )
        self.assertEqual([item["task_id"] for item in projection["jobs"]], ["c", "a", "b"])
        serialized = repr(projection)
        self.assertNotIn("project-a", serialized)
        self.assertNotIn("owner/repo", serialized)
        self.assertNotIn("chat-a", serialized)
        self.assertEqual(projection["secret_fields"], [])


if __name__ == "__main__":
    unittest.main()
