from __future__ import annotations

import hashlib
from pathlib import Path
import tempfile
import unittest

from parking.integration.builder_backend_dispatch import issue_builder_backend_dispatch
from parking.integration.builder_dispatch_runtime import (
    BuilderDispatchReplayError,
    consume_builder_dispatch_once,
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


def make_session(epoch: int = 7) -> dict[str, object]:
    return issue_builder_session(
        chat_id=CHAT,
        project_id=PROJECT,
        repo_scope=REPO,
        session_id=SESSION,
        repo_head=HEAD,
        worktree_digest=WORKTREE,
        state_epoch=epoch,
        capabilities=["file_write", "preview_open"],
        created_at="2026-09-12T15:00:00Z",
        expires_at="2026-09-12T19:00:00Z",
    )


def make_dispatch(sess: dict[str, object]) -> dict[str, object]:
    return issue_builder_backend_dispatch(
        sess,
        chat_id=CHAT,
        project_id=PROJECT,
        repo_scope=REPO,
        session_id=SESSION,
        repo_head=HEAD,
        worktree_digest=WORKTREE,
        state_epoch=7,
        capability="file_write",
        settings_state_digest=SETTINGS,
        backend_id="openbuilder",
        installed=True,
        enabled=True,
        ready=True,
        now=NOW,
    )


def consume(path: Path, row: dict[str, object], sess: dict[str, object], **overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "ledger_path": path,
        "request_id": "request-a",
        "chat_id": CHAT,
        "project_id": PROJECT,
        "repo_scope": REPO,
        "session_id": SESSION,
        "repo_head": HEAD,
        "worktree_digest": WORKTREE,
        "state_epoch": 7,
        "capability": "file_write",
        "settings_state_digest": SETTINGS,
        "installed": True,
        "enabled": True,
        "ready": True,
        "now": NOW,
    }
    values.update(overrides)
    return consume_builder_dispatch_once(row, sess, **values)


class BuilderDispatchRuntimeTests(unittest.TestCase):
    def test_dispatch_is_consumed_exactly_once(self) -> None:
        sess = make_session()
        row = make_dispatch(sess)
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "builder-dispatch.sqlite3"
            self.assertEqual(consume(db, row, sess)["binding_digest"], row["binding_digest"])
            with self.assertRaisesRegex(BuilderDispatchReplayError, "already consumed"):
                consume(db, row, sess, request_id="request-b")

    def test_replay_protection_survives_ledger_reopen(self) -> None:
        sess = make_session()
        row = make_dispatch(sess)
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "builder-dispatch.sqlite3"
            consume(db, row, sess)
            with self.assertRaises(BuilderDispatchReplayError):
                consume(db, row, sess)

    def test_stale_epoch_fails_before_consumption(self) -> None:
        sess = make_session()
        row = make_dispatch(sess)
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "builder-dispatch.sqlite3"
            with self.assertRaisesRegex(PermissionError, "state epoch"):
                consume(db, row, sess, state_epoch=8)
            self.assertFalse(db.exists(), "invalid dispatch must not create durable consume state")

    def test_settings_revocation_fails_before_consumption(self) -> None:
        sess = make_session()
        row = make_dispatch(sess)
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "builder-dispatch.sqlite3"
            with self.assertRaisesRegex(PermissionError, "Captain Settings"):
                consume(db, row, sess, enabled=False)
            self.assertFalse(db.exists(), "revoked backend must not create durable consume state")

    def test_cross_project_replay_fails_before_consumption(self) -> None:
        sess = make_session()
        row = make_dispatch(sess)
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "builder-dispatch.sqlite3"
            with self.assertRaises(PermissionError):
                consume(db, row, sess, project_id="project_b")
            self.assertFalse(db.exists())

    def test_ledger_does_not_persist_raw_scope_or_request_id(self) -> None:
        sess = make_session()
        row = make_dispatch(sess)
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "builder-dispatch.sqlite3"
            consume(db, row, sess, request_id="private-request-id")
            raw = db.read_bytes()
            self.assertNotIn(CHAT.encode(), raw)
            self.assertNotIn(PROJECT.encode(), raw)
            self.assertNotIn(REPO.encode(), raw)
            self.assertNotIn(b"private-request-id", raw)


if __name__ == "__main__":
    unittest.main()
