from __future__ import annotations

import copy
import unittest

from parking.integration.builder_context_bridge import (
    advance_builder_context,
    issue_builder_context,
    validate_builder_context,
)
from parking.integration.builder_session_contract import issue_builder_session


class BuilderContextBridgeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.scope = {
            "chat_id": "chat-alpha",
            "project_id": "project-alpha",
            "repo_scope": "owner/repo#main",
        }
        self.session_args = {
            **self.scope,
            "session_id": "builder-1",
            "repo_head": "a" * 40,
            "worktree_digest": "b" * 64,
            "state_epoch": 4,
        }
        self.session = issue_builder_session(
            **self.session_args,
            capabilities=["context_sync"],
            created_at="2026-09-02T14:00:00Z",
            expires_at="2026-09-02T18:00:00Z",
        )
        self.memory_revision = 12
        self.memory_digest = "c" * 64
        self.builder_revision = 3
        self.builder_digest = "d" * 64
        self.now = "2026-09-02T15:00:00Z"

    def issue(self) -> dict[str, object]:
        return issue_builder_context(
            self.session,
            **self.session_args,
            captain_memory_revision=self.memory_revision,
            captain_memory_digest=self.memory_digest,
            builder_revision=self.builder_revision,
            builder_state_digest=self.builder_digest,
            now=self.now,
        )

    def validate(self, context: dict[str, object], **overrides: object) -> dict[str, object]:
        args = {
            **self.session_args,
            "captain_memory_revision": self.memory_revision,
            "captain_memory_digest": self.memory_digest,
            "builder_revision": self.builder_revision,
            "builder_state_digest": self.builder_digest,
            "now": self.now,
        }
        args.update(overrides)
        return validate_builder_context(context, self.session, **args)

    def test_exact_context_round_trip(self) -> None:
        context = self.issue()
        self.assertEqual(self.validate(context), context)
        self.assertEqual(context["captain_memory_revision"], self.memory_revision)
        self.assertEqual(context["builder_revision"], self.builder_revision)
        self.assertNotIn("prompt", context)
        self.assertNotIn("memory_content", context)

    def test_cross_project_replay_fails_closed(self) -> None:
        context = self.issue()
        with self.assertRaises(PermissionError):
            self.validate(context, project_id="project-other")

    def test_captain_memory_advance_invalidates_builder_context(self) -> None:
        context = self.issue()
        with self.assertRaisesRegex(PermissionError, "Captain memory advanced"):
            self.validate(
                context,
                captain_memory_revision=self.memory_revision + 1,
                captain_memory_digest="e" * 64,
            )

    def test_out_of_band_builder_change_fails_closed(self) -> None:
        context = self.issue()
        with self.assertRaisesRegex(PermissionError, "outside the context bridge"):
            self.validate(
                context,
                builder_revision=self.builder_revision + 1,
                builder_state_digest="e" * 64,
            )

    def test_context_tampering_is_detected(self) -> None:
        context = self.issue()
        tampered = copy.deepcopy(context)
        tampered["builder_state_digest"] = "e" * 64
        with self.assertRaises((PermissionError, ValueError)):
            self.validate(tampered)

    def test_builder_advance_is_exactly_one_revision(self) -> None:
        context = self.issue()
        advanced = advance_builder_context(
            context,
            self.session,
            **self.session_args,
            captain_memory_revision=self.memory_revision,
            captain_memory_digest=self.memory_digest,
            builder_revision=self.builder_revision,
            builder_state_digest=self.builder_digest,
            next_builder_revision=self.builder_revision + 1,
            next_builder_state_digest="e" * 64,
            now=self.now,
        )
        self.assertEqual(advanced["captain_memory_revision"], self.memory_revision)
        self.assertEqual(advanced["captain_memory_digest"], self.memory_digest)
        self.assertEqual(advanced["builder_revision"], self.builder_revision + 1)
        with self.assertRaises(PermissionError):
            advance_builder_context(
                context,
                self.session,
                **self.session_args,
                captain_memory_revision=self.memory_revision,
                captain_memory_digest=self.memory_digest,
                builder_revision=self.builder_revision,
                builder_state_digest=self.builder_digest,
                next_builder_revision=self.builder_revision + 2,
                next_builder_state_digest="f" * 64,
                now=self.now,
            )

    def test_context_sync_capability_is_required(self) -> None:
        no_sync = issue_builder_session(
            **self.session_args,
            capabilities=["file_read"],
            created_at="2026-09-02T14:00:00Z",
            expires_at="2026-09-02T18:00:00Z",
        )
        with self.assertRaisesRegex(PermissionError, "capability denied"):
            issue_builder_context(
                no_sync,
                **self.session_args,
                captain_memory_revision=self.memory_revision,
                captain_memory_digest=self.memory_digest,
                builder_revision=self.builder_revision,
                builder_state_digest=self.builder_digest,
                now=self.now,
            )

    def test_extra_or_secret_like_fields_are_rejected(self) -> None:
        context = self.issue()
        poisoned = copy.deepcopy(context)
        poisoned["api_key"] = "must-not-persist"
        with self.assertRaises(ValueError):
            self.validate(poisoned)


if __name__ == "__main__":
    unittest.main()
