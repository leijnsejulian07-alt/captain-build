from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import unittest

from parking.integration.builder_output_handles import AccessDenied, BuilderOutputHandleStore
from parking.integration.builder_session_contract import issue_builder_session
from parking.integration.builder_session_store import BuilderSessionAuthorityStore
from parking.integration.project_epoch_transition import apply_project_epoch_transition
from parking.integration.project_memory_context_store import ProjectMemoryContextStore

CHAT = "chat-a"
PROJECT = "project-a"
OTHER_PROJECT = "project-b"
REPO = "owner/repo-a"
OTHER_REPO = "owner/repo-b"
HEAD = "a" * 40
WORKTREE = "b" * 64
NOW = "2026-09-15T00:10:00+00:00"
HANDLE_NOW = 1_789_430_000


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def builder_session(*, session_id: str, project_id: str, repo_scope: str, epoch: int) -> dict[str, object]:
    created = datetime(2026, 9, 15, 0, 0, tzinfo=timezone.utc)
    return issue_builder_session(
        chat_id=CHAT,
        project_id=project_id,
        repo_scope=repo_scope,
        session_id=session_id,
        repo_head=HEAD,
        worktree_digest=WORKTREE,
        state_epoch=epoch,
        capabilities=["file_read", "preview_open"],
        created_at=created.isoformat(),
        expires_at=(created + timedelta(hours=2)).isoformat(),
    )


class IntegratedEpochIsolationTests(unittest.TestCase):
    def test_one_transition_revokes_all_stale_exact_scope_resources(self) -> None:
        scope = dict(chat_id=CHAT, project_id=PROJECT, repo_scope=REPO)
        other_scope = dict(chat_id=CHAT, project_id=OTHER_PROJECT, repo_scope=OTHER_REPO)

        outputs = BuilderOutputHandleStore(b"o" * 32)
        stale_output = outputs.issue(
            kind="preview", epoch=1, builder_session_id="builder-old", revision=1,
            artifact_digest=digest("stale-preview"), now=HANDLE_NOW, **scope,
        )
        current_output = outputs.issue(
            kind="preview", epoch=2, builder_session_id="builder-current", revision=2,
            artifact_digest=digest("current-preview"), now=HANDLE_NOW, **scope,
        )
        other_output = outputs.issue(
            kind="preview", epoch=1, builder_session_id="builder-other", revision=1,
            artifact_digest=digest("other-preview"), now=HANDLE_NOW, **other_scope,
        )

        memory = ProjectMemoryContextStore()
        memory.register(kind="project_memory", state_epoch=1, record_id="memory-old", **scope)
        memory.register(kind="project_context", state_epoch=1, record_id="context-old", **scope)
        memory.register(kind="project_memory", state_epoch=2, record_id="memory-current", **scope)
        memory.register(kind="project_memory", state_epoch=1, record_id="memory-other", **other_scope)

        sessions = BuilderSessionAuthorityStore()
        stale_session = builder_session(session_id="builder-old", project_id=PROJECT, repo_scope=REPO, epoch=1)
        current_session = builder_session(session_id="builder-current", project_id=PROJECT, repo_scope=REPO, epoch=2)
        other_session = builder_session(session_id="builder-other", project_id=OTHER_PROJECT, repo_scope=OTHER_REPO, epoch=1)
        sessions.register(stale_session, **scope)
        sessions.register(current_session, **scope)
        sessions.register(other_session, **other_scope)

        result = apply_project_epoch_transition(
            previous_epoch=1,
            current_epoch=2,
            builder_outputs=outputs,
            additional_cleanups={"builder_sessions": sessions, "memory_context": memory},
            **scope,
        )

        self.assertEqual(
            result.cleanup_counts,
            (("builder_outputs", 1), ("builder_sessions", 1), ("memory_context", 2)),
        )

        with self.assertRaises(AccessDenied):
            outputs.resolve(
                stale_output, expected_kind="preview", current_epoch=2,
                builder_session_id="builder-old", now=HANDLE_NOW + 1, **scope,
            )
        self.assertEqual(
            outputs.resolve(
                current_output, expected_kind="preview", current_epoch=2,
                builder_session_id="builder-current", now=HANDLE_NOW + 1, **scope,
            )["epoch"],
            2,
        )
        self.assertEqual(
            outputs.resolve(
                other_output, expected_kind="preview", current_epoch=1,
                builder_session_id="builder-other", now=HANDLE_NOW + 1, **other_scope,
            )["epoch"],
            1,
        )

        with self.assertRaises(PermissionError):
            memory.authorize("memory-old", current_epoch=2, **scope)
        with self.assertRaises(PermissionError):
            memory.authorize("context-old", current_epoch=2, **scope)
        self.assertEqual(memory.authorize("memory-current", current_epoch=2, **scope).record_id, "memory-current")
        self.assertEqual(memory.authorize("memory-other", current_epoch=1, **other_scope).record_id, "memory-other")

        with self.assertRaises(PermissionError):
            sessions.authorize(
                stale_session, session_id="builder-old", repo_head=HEAD, worktree_digest=WORKTREE,
                state_epoch=1, capability="file_read", now=NOW, **scope,
            )
        self.assertEqual(
            sessions.authorize(
                current_session, session_id="builder-current", repo_head=HEAD, worktree_digest=WORKTREE,
                state_epoch=2, capability="file_read", now=NOW, **scope,
            ).state_epoch,
            2,
        )
        self.assertEqual(
            sessions.authorize(
                other_session, session_id="builder-other", repo_head=HEAD, worktree_digest=WORKTREE,
                state_epoch=1, capability="file_read", now=NOW, **other_scope,
            ).state_epoch,
            1,
        )

        again = apply_project_epoch_transition(
            previous_epoch=1,
            current_epoch=2,
            builder_outputs=outputs,
            additional_cleanups={"builder_sessions": sessions, "memory_context": memory},
            **scope,
        )
        self.assertEqual(
            again.cleanup_counts,
            (("builder_outputs", 0), ("builder_sessions", 0), ("memory_context", 0)),
        )

    def test_cross_project_resources_never_authorize_under_target_scope(self) -> None:
        target = dict(chat_id=CHAT, project_id=PROJECT, repo_scope=REPO)
        other = dict(chat_id=CHAT, project_id=OTHER_PROJECT, repo_scope=OTHER_REPO)

        memory = ProjectMemoryContextStore()
        memory.register(kind="project_memory", state_epoch=2, record_id="other-memory", **other)
        with self.assertRaises(PermissionError):
            memory.authorize("other-memory", current_epoch=2, **target)

        sessions = BuilderSessionAuthorityStore()
        other_session = builder_session(session_id="other-session", project_id=OTHER_PROJECT, repo_scope=OTHER_REPO, epoch=2)
        sessions.register(other_session, **other)
        with self.assertRaises(PermissionError):
            sessions.authorize(
                other_session, session_id="other-session", repo_head=HEAD, worktree_digest=WORKTREE,
                state_epoch=2, capability="file_read", now=NOW, **target,
            )


if __name__ == "__main__":
    unittest.main()
