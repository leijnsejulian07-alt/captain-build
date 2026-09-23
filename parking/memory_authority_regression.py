"""Executable regressions for Captain project-memory epoch isolation."""
from memory_authority import MemoryAuthority, MemoryAuthorityError, project_memory_visible

H = "a" * 64
BASE = {"chat_id": "chat-a", "project_id": "project-a", "repo_scope_hash": H, "state_epoch": 7}


def rejected(value):
    try:
        MemoryAuthority.parse(value)
    except MemoryAuthorityError:
        return True
    return False


def run():
    assert project_memory_visible(BASE, BASE)
    for field, replacement in (
        ("chat_id", "chat-b"),
        ("project_id", "project-b"),
        ("repo_scope_hash", "b" * 64),
        ("state_epoch", 8),
    ):
        stale = dict(BASE)
        stale[field] = replacement
        assert not project_memory_visible(stale, BASE), field

    assert rejected({**BASE, "state_epoch": 0})
    assert rejected({**BASE, "state_epoch": True})
    assert rejected({**BASE, "repo_scope_hash": "C:/raw/project"})
    assert rejected({k: v for k, v in BASE.items() if k != "project_id"})
    assert rejected({**BASE, "repo_scope": "raw/path"})
    assert not project_memory_visible({**BASE, "state_epoch": "7"}, BASE)

    # Normal non-project chat must stay outside this project-memory parser.
    normal_chat = {"chat_id": "ordinary-chat", "message": "hello"}
    assert rejected(normal_chat)
    print("PASS: project memory authority is exact, epoch-bound and fail-closed")


if __name__ == "__main__":
    run()
