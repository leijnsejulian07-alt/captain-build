"""Provider-free regression for Captain's canonical ProjectAuthority runtime."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from captain.project_authority import (  # noqa: E402
    AuthorityError,
    ProjectAuthority,
    ScopedRecord,
    require_current_epoch,
)


def denied(fn):
    try:
        fn()
    except AuthorityError:
        return
    raise AssertionError("authority check unexpectedly allowed access")


def test_normal_chat_stays_low_friction():
    normal = ProjectAuthority()
    normal.validate()
    require_current_epoch(normal, current_epoch=0)
    assert ScopedRecord(normal, generic=True, project_specific=False).readable_by(normal)


def test_partial_authority_fails_closed():
    invalid = (
        ProjectAuthority(chat_id="c"),
        ProjectAuthority(project_id="p"),
        ProjectAuthority(repo_scope="r"),
        ProjectAuthority(state_epoch=1),
        ProjectAuthority("c", "p", "r", True),
        ProjectAuthority("c", "p", "r", -1),
        ProjectAuthority(" ", "p", "r", 1),
    )
    for authority in invalid:
        denied(authority.validate)


def test_chat_project_repo_and_epoch_are_all_authority_walls():
    current = ProjectAuthority("chat-a", "project-a", "repo/a", 7)
    record = ScopedRecord(current)
    assert record.readable_by(current)

    for mismatch in (
        ProjectAuthority("chat-b", "project-a", "repo/a", 7),
        ProjectAuthority("chat-a", "project-b", "repo/a", 7),
        ProjectAuthority("chat-a", "project-a", "repo/b", 7),
        ProjectAuthority("chat-a", "project-a", "repo/a", 6),
        ProjectAuthority("chat-a", "project-a", "repo/a", 8),
    ):
        assert not record.readable_by(mismatch)
        denied(lambda mismatch=mismatch: current.require_same_owner(mismatch))


def test_active_epoch_rejects_stale_and_future_state():
    current = ProjectAuthority("chat-a", "project-a", "repo/a", 7)
    require_current_epoch(current, current_epoch=7)
    denied(lambda: require_current_epoch(current, current_epoch=8))
    denied(lambda: require_current_epoch(ProjectAuthority("chat-a", "project-a", "repo/a", 8), current_epoch=7))


def test_project_memory_never_leaks_to_normal_chat():
    project = ProjectAuthority("chat-a", "project-a", "repo/a", 7)
    assert not ScopedRecord(project).readable_by(ProjectAuthority())


def test_only_explicit_global_distilled_learning_may_enter_project():
    project = ProjectAuthority("chat-a", "project-a", "repo/a", 7)
    global_scope = ProjectAuthority()

    assert ScopedRecord(global_scope, generic=True, project_specific=False).readable_by(project)
    assert not ScopedRecord(global_scope, generic=False, project_specific=False).readable_by(project)
    assert not ScopedRecord(global_scope, generic=True, project_specific=True).readable_by(project)


if __name__ == "__main__":
    test_normal_chat_stays_low_friction()
    test_partial_authority_fails_closed()
    test_chat_project_repo_and_epoch_are_all_authority_walls()
    test_active_epoch_rejects_stale_and_future_state()
    test_project_memory_never_leaks_to_normal_chat()
    test_only_explicit_global_distilled_learning_may_enter_project()
    print("PROJECT_AUTHORITY_RUNTIME_HARDENED_PASS")
