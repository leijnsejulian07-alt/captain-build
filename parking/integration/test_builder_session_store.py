from datetime import datetime, timedelta, timezone
import unittest

from parking.integration.builder_session_contract import issue_builder_session
from parking.integration.builder_session_store import BuilderSessionAuthorityStore, BuilderSessionStoreError
from parking.integration.project_epoch_transition import apply_project_epoch_transition


CHAT = "chat-a"
PROJECT = "project-a"
REPO = "owner/repo"
HEAD = "a" * 40
WORKTREE = "b" * 64


def session(session_id: str, epoch: int) -> dict[str, object]:
    created = datetime(2026, 9, 14, 12, tzinfo=timezone.utc)
    return issue_builder_session(
        chat_id=CHAT, project_id=PROJECT, repo_scope=REPO,
        session_id=session_id, repo_head=HEAD, worktree_digest=WORKTREE,
        state_epoch=epoch, capabilities=["file_read", "preview_open"],
        created_at=created.isoformat(), expires_at=(created + timedelta(hours=2)).isoformat(),
    )


class FakeOutputs:
    def __init__(self) -> None:
        self.calls = 0

    def revoke_stale_epochs(self, **_: object) -> int:
        self.calls += 1
        return 2


class BuilderSessionStoreTests(unittest.TestCase):
    def test_current_session_authorizes(self) -> None:
        store = BuilderSessionAuthorityStore()
        issued = session("builder-1", 2)
        store.register(issued, chat_id=CHAT, project_id=PROJECT, repo_scope=REPO)
        ref = store.authorize(
            issued, chat_id=CHAT, project_id=PROJECT, repo_scope=REPO,
            session_id="builder-1", repo_head=HEAD, worktree_digest=WORKTREE,
            state_epoch=2, capability="file_read", now="2026-09-14T13:00:00+00:00",
        )
        self.assertEqual(ref.state_epoch, 2)

    def test_cross_scope_and_epoch_fail_closed(self) -> None:
        store = BuilderSessionAuthorityStore()
        issued = session("builder-1", 2)
        store.register(issued, chat_id=CHAT, project_id=PROJECT, repo_scope=REPO)
        with self.assertRaises(PermissionError):
            store.authorize(issued, chat_id=CHAT, project_id="project-b", repo_scope=REPO,
                session_id="builder-1", repo_head=HEAD, worktree_digest=WORKTREE,
                state_epoch=2, capability="file_read", now="2026-09-14T13:00:00+00:00")
        with self.assertRaises(PermissionError):
            store.authorize(issued, chat_id=CHAT, project_id=PROJECT, repo_scope=REPO,
                session_id="builder-1", repo_head=HEAD, worktree_digest=WORKTREE,
                state_epoch=3, capability="file_read", now="2026-09-14T13:00:00+00:00")

    def test_epoch_transition_revokes_stale_session_authority(self) -> None:
        store = BuilderSessionAuthorityStore()
        stale = session("builder-old", 1)
        current = session("builder-current", 2)
        store.register(stale, chat_id=CHAT, project_id=PROJECT, repo_scope=REPO)
        store.register(current, chat_id=CHAT, project_id=PROJECT, repo_scope=REPO)
        other = issue_builder_session(
            chat_id=CHAT, project_id="project-b", repo_scope=REPO, session_id="other",
            repo_head=HEAD, worktree_digest=WORKTREE, state_epoch=1,
            capabilities=["file_read"], created_at="2026-09-14T12:00:00+00:00",
            expires_at="2026-09-14T14:00:00+00:00")
        store.register(other, chat_id=CHAT, project_id="project-b", repo_scope=REPO)
        result = apply_project_epoch_transition(
            chat_id=CHAT, project_id=PROJECT, repo_scope=REPO,
            previous_epoch=1, current_epoch=2, builder_outputs=FakeOutputs(),
            additional_cleanups={"builder_sessions": store},
        )
        self.assertIn(("builder_sessions", 1), result.cleanup_counts)
        self.assertEqual(store.count(), 2)
        with self.assertRaises(PermissionError):
            store.authorize(stale, chat_id=CHAT, project_id=PROJECT, repo_scope=REPO,
                session_id="builder-old", repo_head=HEAD, worktree_digest=WORKTREE,
                state_epoch=1, capability="file_read", now="2026-09-14T13:00:00+00:00")
        store.authorize(current, chat_id=CHAT, project_id=PROJECT, repo_scope=REPO,
            session_id="builder-current", repo_head=HEAD, worktree_digest=WORKTREE,
            state_epoch=2, capability="file_read", now="2026-09-14T13:00:00+00:00")

    def test_same_id_cannot_rebind_and_cleanup_is_idempotent(self) -> None:
        store = BuilderSessionAuthorityStore()
        first = session("builder-1", 1)
        store.register(first, chat_id=CHAT, project_id=PROJECT, repo_scope=REPO)
        with self.assertRaises(BuilderSessionStoreError):
            store.register(session("builder-1", 2), chat_id=CHAT, project_id=PROJECT, repo_scope=REPO)
        self.assertEqual(store.revoke_stale_epochs(chat_id=CHAT, project_id=PROJECT, repo_scope=REPO, current_epoch=2), 1)
        self.assertEqual(store.revoke_stale_epochs(chat_id=CHAT, project_id=PROJECT, repo_scope=REPO, current_epoch=2), 0)

    def test_invalid_epoch_fails_closed(self) -> None:
        store = BuilderSessionAuthorityStore()
        with self.assertRaises(BuilderSessionStoreError):
            store.revoke_stale_epochs(chat_id=CHAT, project_id=PROJECT, repo_scope=REPO, current_epoch=True)


if __name__ == "__main__":
    unittest.main()
