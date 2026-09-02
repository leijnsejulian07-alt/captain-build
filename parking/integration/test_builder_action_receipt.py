from __future__ import annotations

import copy
import unittest

from parking.integration.builder_action_receipt import (
    issue_builder_action_receipt,
    validate_builder_action_receipt,
)


D1 = "1" * 64
D2 = "2" * 64
D3 = "3" * 64
D4 = "4" * 64
D5 = "5" * 64


class BuilderActionReceiptTests(unittest.TestCase):
    def issue(self):
        return issue_builder_action_receipt(
            chat_id="chat-a",
            project_id="project-a",
            repo_scope="owner/repo@worktree-a",
            request_id="req-1",
            action="tests",
            session_binding=D1,
            context_binding=D2,
            before_state_digest=D3,
            after_state_digest=D4,
            artifact_digest=D5,
            result="succeeded",
            started_at="2026-09-02T15:00:00Z",
            finished_at="2026-09-02T15:00:05Z",
        )

    def validate(self, receipt, **overrides):
        args = dict(
            chat_id="chat-a",
            project_id="project-a",
            repo_scope="owner/repo@worktree-a",
            request_id="req-1",
            action="tests",
            session_binding=D1,
            context_binding=D2,
            before_state_digest=D3,
            after_state_digest=D4,
            artifact_digest=D5,
            now="2026-09-02T15:01:00Z",
        )
        args.update(overrides)
        return validate_builder_action_receipt(receipt, **args)

    def test_round_trip(self):
        receipt = self.issue()
        self.assertEqual(self.validate(receipt), receipt)

    def test_cross_project_replay_fails_closed(self):
        with self.assertRaises(PermissionError):
            self.validate(self.issue(), project_id="project-b")

    def test_session_or_context_replay_fails_closed(self):
        with self.assertRaises(PermissionError):
            self.validate(self.issue(), context_binding="6" * 64)

    def test_artifact_substitution_fails_closed(self):
        with self.assertRaises(PermissionError):
            self.validate(self.issue(), artifact_digest="7" * 64)

    def test_receipt_tampering_is_detected(self):
        receipt = copy.deepcopy(self.issue())
        receipt["result"] = "failed"
        with self.assertRaises(ValueError):
            self.validate(receipt)

    def test_extra_or_secret_like_fields_are_rejected(self):
        receipt = copy.deepcopy(self.issue())
        receipt["access_token"] = "must-not-persist"
        with self.assertRaises(ValueError):
            self.validate(receipt)

    def test_future_receipt_fails_closed(self):
        with self.assertRaises(PermissionError):
            self.validate(self.issue(), now="2026-09-02T14:59:59Z")

    def test_stale_receipt_fails_closed(self):
        with self.assertRaises(PermissionError):
            self.validate(self.issue(), now="2026-09-03T15:01:00Z")

    def test_unbounded_action_duration_is_rejected(self):
        with self.assertRaises(ValueError):
            issue_builder_action_receipt(
                chat_id="chat-a",
                project_id="project-a",
                repo_scope="owner/repo@worktree-a",
                request_id="req-2",
                action="tests",
                session_binding=D1,
                context_binding=D2,
                before_state_digest=D3,
                after_state_digest=D4,
                artifact_digest=D5,
                result="failed",
                started_at="2026-09-01T00:00:00Z",
                finished_at="2026-09-02T00:00:01Z",
            )


if __name__ == "__main__":
    unittest.main()
