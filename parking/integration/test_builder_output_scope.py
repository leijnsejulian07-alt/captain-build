from __future__ import annotations

import copy
import hashlib
import unittest

from parking.integration.builder_output_scope import authorize_builder_output, issue_builder_output
from parking.integration.builder_session_contract import issue_builder_session


class BuilderOutputScopeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.scope = {
            "chat_id": "chat-a",
            "project_id": "project-a",
            "repo_scope": "repo://captain/a",
            "session_id": "builder-1",
            "repo_head": "a" * 40,
            "worktree_digest": "b" * 64,
            "state_epoch": 7,
        }
        self.session = issue_builder_session(
            **self.scope,
            capabilities=["console_read", "diff_read", "file_read", "preview_open"],
            created_at="2026-09-12T17:00:00+00:00",
            expires_at="2026-09-12T18:00:00+00:00",
        )
        self.output = issue_builder_output(
            session=self.session,
            output_id="preview-main",
            kind="preview",
            revision=1,
            content_digest=hashlib.sha256(b"preview-v1").hexdigest(),
        )

    def authorize(self, *, output=None, session=None, **overrides):
        args = dict(self.scope)
        args.update(overrides)
        return authorize_builder_output(
            self.output if output is None else output,
            session=self.session if session is None else session,
            now="2026-09-12T17:30:00+00:00",
            **args,
        )

    def test_exact_current_scope_is_authorized(self):
        authorized = self.authorize()
        self.assertEqual(authorized["output_id"], "preview-main")
        self.assertEqual(authorized["state_epoch"], 7)

    def test_stale_output_is_inaccessible_after_epoch_rotation(self):
        with self.assertRaises(PermissionError):
            self.authorize(state_epoch=8)

    def test_cross_project_and_repo_access_fail_closed(self):
        with self.assertRaises(PermissionError):
            self.authorize(project_id="project-b")
        with self.assertRaises(PermissionError):
            self.authorize(repo_scope="repo://captain/b")

    def test_output_cannot_be_rebound_to_new_session(self):
        replacement = issue_builder_session(
            chat_id="chat-a",
            project_id="project-a",
            repo_scope="repo://captain/a",
            session_id="builder-2",
            repo_head="a" * 40,
            worktree_digest="b" * 64,
            state_epoch=7,
            capabilities=["console_read", "diff_read", "file_read", "preview_open"],
            created_at="2026-09-12T17:00:00+00:00",
            expires_at="2026-09-12T18:00:00+00:00",
        )
        with self.assertRaises(PermissionError):
            authorize_builder_output(
                self.output,
                session=replacement,
                chat_id="chat-a",
                project_id="project-a",
                repo_scope="repo://captain/a",
                session_id="builder-2",
                repo_head="a" * 40,
                worktree_digest="b" * 64,
                state_epoch=7,
                now="2026-09-12T17:30:00+00:00",
            )

    def test_kind_requires_corresponding_session_capability(self):
        limited = issue_builder_session(
            **self.scope,
            capabilities=["file_read"],
            created_at="2026-09-12T17:00:00+00:00",
            expires_at="2026-09-12T18:00:00+00:00",
        )
        preview = issue_builder_output(
            session=limited,
            output_id="preview-main",
            kind="preview",
            revision=1,
            content_digest="c" * 64,
        )
        with self.assertRaises(PermissionError):
            self.authorize(output=preview, session=limited)

    def test_tampered_output_metadata_is_rejected(self):
        tampered = copy.deepcopy(self.output)
        tampered["revision"] = 2
        with self.assertRaises(ValueError):
            self.authorize(output=tampered)

    def test_handle_does_not_persist_raw_scope_or_output_body(self):
        serialized = repr(self.output)
        self.assertNotIn("chat-a", serialized)
        self.assertNotIn("project-a", serialized)
        self.assertNotIn("repo://captain/a", serialized)
        self.assertNotIn("preview-v1", serialized)
        self.assertEqual(
            set(self.output),
            {
                "schema_version",
                "session_binding_digest",
                "state_epoch",
                "output_id",
                "kind",
                "revision",
                "content_digest",
                "output_binding_digest",
            },
        )


if __name__ == "__main__":
    unittest.main()
