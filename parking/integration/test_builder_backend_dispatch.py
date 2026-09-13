from __future__ import annotations

import copy
import hashlib
import unittest

from parking.integration.builder_backend_dispatch import (
    issue_builder_backend_dispatch,
    validate_builder_backend_dispatch,
)
from parking.integration.builder_session_contract import issue_builder_session

CHAT = "chat_a"
PROJECT = "project_a"
REPO = "owner/repo#feature"
SESSION = "builder_a"
HEAD = "a" * 40
WORKTREE = hashlib.sha256(b"worktree").hexdigest()
SETTINGS = hashlib.sha256(b"settings-v1").hexdigest()
NOW = "2026-09-12T16:00:00Z"


def session(*, epoch: int = 7) -> dict[str, object]:
    return issue_builder_session(
        chat_id=CHAT, project_id=PROJECT, repo_scope=REPO, session_id=SESSION,
        repo_head=HEAD, worktree_digest=WORKTREE, state_epoch=epoch,
        capabilities=["file_read", "file_write", "preview_open", "test_run"],
        created_at="2026-09-12T15:00:00Z", expires_at="2026-09-12T19:00:00Z",
    )


def issue(row: dict[str, object], **overrides: object) -> dict[str, object]:
    values = {
        "chat_id": CHAT, "project_id": PROJECT, "repo_scope": REPO, "session_id": SESSION,
        "repo_head": HEAD, "worktree_digest": WORKTREE, "state_epoch": 7,
        "capability": "file_write", "settings_state_digest": SETTINGS,
        "backend_id": "openbuilder", "installed": True, "enabled": True, "ready": True,
        "now": NOW,
    }
    values.update(overrides)
    return issue_builder_backend_dispatch(row, **values)


def validate(row: dict[str, object], sess: dict[str, object] | None = None, **overrides: object) -> dict[str, object]:
    values = {
        "chat_id": CHAT, "project_id": PROJECT, "repo_scope": REPO, "session_id": SESSION,
        "repo_head": HEAD, "worktree_digest": WORKTREE, "state_epoch": 7,
        "capability": "file_write", "settings_state_digest": SETTINGS,
        "installed": True, "enabled": True, "ready": True, "now": NOW,
    }
    values.update(overrides)
    return validate_builder_backend_dispatch(row, session() if sess is None else sess, **values)


class BuilderBackendDispatchTests(unittest.TestCase):
    def test_openbuilder_is_default_bounded_backend(self) -> None:
        row = issue(session())
        self.assertEqual(row["backend_id"], "openbuilder")
        self.assertEqual(row["authority"], "captain")
        self.assertEqual(row["execution_mode"], "local")
        self.assertEqual(validate(row)["binding_digest"], row["binding_digest"])

    def test_optional_backends_require_explicit_selection(self) -> None:
        with self.assertRaisesRegex(PermissionError, "explicit Captain selection"):
            issue(session(), backend_id="freebuff")
        row = issue(session(), backend_id="freebuff", allow_optional_backend=True)
        self.assertEqual(row["adapter_kind"], "sdk")

    def test_unknown_backend_substitution_fails_closed(self) -> None:
        with self.assertRaisesRegex(PermissionError, "allowlisted"):
            issue(session(), backend_id="rogue-router")

    def test_settings_readiness_is_mandatory_at_issue_and_execution(self) -> None:
        for field in ("installed", "enabled", "ready"):
            with self.subTest(issue_field=field):
                with self.assertRaisesRegex(PermissionError, "Captain Settings"):
                    issue(session(), **{field: False})
        row = issue(session())
        for field in ("installed", "enabled", "ready"):
            with self.subTest(validate_field=field):
                with self.assertRaisesRegex(PermissionError, "Captain Settings"):
                    validate(row, **{field: False})

    def test_settings_change_revokes_existing_dispatch(self) -> None:
        row = issue(session())
        changed = hashlib.sha256(b"settings-v2-disabled").hexdigest()
        with self.assertRaisesRegex(PermissionError, "Settings changed"):
            validate(row, settings_state_digest=changed)

    def test_remote_and_paid_execution_require_separate_approval(self) -> None:
        with self.assertRaisesRegex(PermissionError, "remote builder execution"):
            issue(session(), backend_id="opencode", allow_optional_backend=True, execution_mode="remote-free")
        with self.assertRaisesRegex(PermissionError, "paid builder execution"):
            issue(
                session(), backend_id="opencode", allow_optional_backend=True,
                execution_mode="remote-paid", allow_remote_execution=True,
            )
        row = issue(
            session(), backend_id="opencode", allow_optional_backend=True,
            execution_mode="remote-paid", allow_remote_execution=True, allow_paid_execution=True,
        )
        self.assertEqual(row["execution_mode"], "remote-paid")

    def test_openbuilder_cannot_be_silently_moved_remote(self) -> None:
        with self.assertRaisesRegex(PermissionError, "does not permit remote"):
            issue(session(), execution_mode="remote-free", allow_remote_execution=True)

    def test_epoch_and_scope_walls_remain_fail_closed(self) -> None:
        row = issue(session())
        with self.assertRaisesRegex(PermissionError, "state epoch"):
            validate(row, state_epoch=8)
        with self.assertRaisesRegex(PermissionError, "scope"):
            validate(row, project_id="project_b")

    def test_capability_and_session_binding_cannot_be_replayed(self) -> None:
        row = issue(session())
        with self.assertRaisesRegex(PermissionError, "capability"):
            validate(row, capability="preview_open")
        changed_workspace = hashlib.sha256(b"other-worktree").hexdigest()
        with self.assertRaisesRegex(PermissionError, "workspace changed"):
            validate(row, worktree_digest=changed_workspace)

    def test_tampering_or_secret_extension_is_rejected(self) -> None:
        row = issue(session())
        tampered = copy.deepcopy(row)
        tampered["backend_id"] = "freebuff"
        with self.assertRaises((PermissionError, ValueError)):
            validate(tampered)
        with_secret = copy.deepcopy(row)
        with_secret["api_key"] = "must-not-persist"
        with self.assertRaisesRegex(ValueError, "schema"):
            validate(with_secret)


if __name__ == "__main__":
    unittest.main()
