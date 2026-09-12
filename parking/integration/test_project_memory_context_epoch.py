import unittest

from parking.integration.project_memory_context_epoch import (
    MemoryContextRecord,
    ProjectStateEpoch,
    authorize_normal_chat,
)


class ProjectMemoryContextEpochTests(unittest.TestCase):
    def setUp(self):
        self.scope = {
            "chat_id": "chat-alpha",
            "project_id": "project-alpha",
            "repo_scope": "leijnsejulian07-alt/example#refs/heads/main",
        }
        self.active = ProjectStateEpoch.create(self.scope, 7)

    def _record(self, kind="project_memory", *, scope=None, epoch=7, record_id="memory-1"):
        return MemoryContextRecord(
            kind=kind,
            scope=ProjectStateEpoch.create(scope or self.scope, epoch).scope,
            state_epoch=epoch,
            record_id=record_id,
        )

    def test_current_epoch_project_memory_is_accessible(self):
        self._record().authorize(self.active, requesting_chat_id="chat-alpha")

    def test_stale_project_memory_is_inaccessible_after_epoch_change(self):
        stale = self._record(epoch=7)
        rotated = ProjectStateEpoch.create(self.scope, 8)
        with self.assertRaises(PermissionError):
            stale.authorize(rotated, requesting_chat_id="chat-alpha")

    def test_stale_project_context_is_inaccessible_after_epoch_change(self):
        stale = self._record(kind="project_context", epoch=7, record_id="context-1")
        rotated = ProjectStateEpoch.create(self.scope, 8)
        with self.assertRaises(PermissionError):
            stale.authorize(rotated, requesting_chat_id="chat-alpha")

    def test_stale_chat_context_is_inaccessible_after_epoch_change(self):
        stale = self._record(kind="chat_context", epoch=7, record_id="chat-context-1")
        rotated = ProjectStateEpoch.create(self.scope, 8)
        with self.assertRaises(PermissionError):
            stale.authorize(rotated, requesting_chat_id="chat-alpha")

    def test_cross_project_repo_and_chat_access_fail_closed(self):
        record = self._record()
        variants = (
            dict(self.scope, chat_id="chat-beta"),
            dict(self.scope, project_id="project-beta"),
            dict(self.scope, repo_scope="leijnsejulian07-alt/other#refs/heads/main"),
        )
        for other_scope in variants:
            with self.subTest(other_scope=other_scope):
                other = ProjectStateEpoch.create(other_scope, 7)
                with self.assertRaises(PermissionError):
                    record.authorize(other, requesting_chat_id=other_scope["chat_id"])

    def test_chat_context_requires_exact_chat_owner(self):
        record = self._record(kind="chat_context", record_id="chat-context-1")
        with self.assertRaises(PermissionError):
            record.authorize(self.active)
        with self.assertRaises(PermissionError):
            record.authorize(self.active, requesting_chat_id="chat-beta")
        record.authorize(self.active, requesting_chat_id="chat-alpha")

    def test_project_memory_cannot_be_read_by_foreign_requesting_chat(self):
        record = self._record()
        with self.assertRaises(PermissionError):
            record.authorize(self.active, requesting_chat_id="chat-beta")

    def test_normal_non_project_chat_remains_usable(self):
        self.assertIsNone(authorize_normal_chat(project_id=None, repo_scope=None, state_epoch=None))

    def test_partial_project_authority_is_rejected_for_normal_chat(self):
        cases = (
            {"project_id": "project-alpha", "repo_scope": None, "state_epoch": None},
            {"project_id": None, "repo_scope": "owner/repo", "state_epoch": None},
            {"project_id": None, "repo_scope": None, "state_epoch": 1},
            {"project_id": "project-alpha", "repo_scope": "owner/repo", "state_epoch": 1},
        )
        for case in cases:
            with self.subTest(case=case):
                with self.assertRaises(PermissionError):
                    authorize_normal_chat(**case)

    def test_invalid_epochs_fail_closed(self):
        for epoch in (0, -1, True, "7"):
            with self.subTest(epoch=epoch):
                with self.assertRaises(ValueError):
                    ProjectStateEpoch.create(self.scope, epoch)

    def test_invalid_memory_context_kinds_and_ids_fail_closed(self):
        bad_records = (
            MemoryContextRecord("task", self.active.scope, 7, "record-1"),
            MemoryContextRecord("project_memory", self.active.scope, 0, "record-1"),
            MemoryContextRecord("project_memory", self.active.scope, 7, ""),
            MemoryContextRecord("project_memory", self.active.scope, 7, "x" * 161),
        )
        for record in bad_records:
            with self.subTest(record=record):
                with self.assertRaises(ValueError):
                    record.validate()


if __name__ == "__main__":
    unittest.main()
