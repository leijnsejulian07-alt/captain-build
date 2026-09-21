"""Parking regression for Captain Project Memory/context epoch isolation.
Pure contract test: no repo-authored commands or external code are executed.
"""
from copy import deepcopy


def project_record_visible(record, current):
    """Project-scoped memory/context is readable only inside its exact current epoch wall."""
    if not isinstance(record, dict) or not isinstance(current, dict):
        return False
    if record.get("version") != 1 or record.get("kind") not in {"project_memory", "project_context"}:
        return False
    scope = record.get("scope")
    if not isinstance(scope, dict):
        return False
    for key in ("chat_id", "project_id", "state_epoch"):
        if key not in scope or scope[key] != current.get(key):
            return False
    # repo_scope is optional, but when bound it is an additional wall.
    bound_repo = scope.get("repo_scope")
    if bound_repo is not None and bound_repo != current.get("repo_scope"):
        return False
    return isinstance(record.get("payload"), dict)


def normal_chat_record_visible(record, current):
    """Non-project chat remains independent of Project State epochs."""
    if current.get("project_id") is not None:
        return False
    return isinstance(record, dict) and record.get("kind") == "chat_memory" and record.get("chat_id") == current.get("chat_id")


def fixture(kind="project_memory", repo_scope="repo-a"):
    record = {
        "version": 1,
        "scope": {"chat_id": "chat-a", "project_id": "project-a", "repo_scope": repo_scope, "state_epoch": 9},
        "kind": kind,
        "created_at": "2026-09-21T04:00:00Z",
        "payload": {"summary": "scoped"},
    }
    current = {"chat_id": "chat-a", "project_id": "project-a", "repo_scope": "repo-a", "state_epoch": 9}
    return record, current


def test_owner_epoch_can_read_memory_and_context():
    for kind in ("project_memory", "project_context"):
        record, current = fixture(kind)
        assert project_record_visible(record, current)


def test_epoch_change_makes_old_memory_and_context_inaccessible():
    for kind in ("project_memory", "project_context"):
        record, current = fixture(kind)
        current["state_epoch"] += 1
        assert not project_record_visible(record, current)


def test_project_and_chat_walls_fail_closed():
    for key in ("chat_id", "project_id"):
        record, current = fixture()
        current[key] += "-other"
        assert not project_record_visible(record, current), key


def test_bound_repo_is_an_additional_wall():
    record, current = fixture()
    current["repo_scope"] = "repo-b"
    assert not project_record_visible(record, current)
    record, current = fixture(repo_scope=None)
    current["repo_scope"] = "repo-b"
    assert project_record_visible(record, current)


def test_missing_epoch_fails_closed():
    record, current = fixture()
    del record["scope"]["state_epoch"]
    assert not project_record_visible(record, current)


def test_normal_non_project_chat_not_broken_by_epoch_rules():
    record = {"kind": "chat_memory", "chat_id": "chat-normal", "payload": {"summary": "hello"}}
    assert normal_chat_record_visible(record, {"chat_id": "chat-normal", "project_id": None})
    assert not normal_chat_record_visible(record, {"chat_id": "chat-other", "project_id": None})


if __name__ == "__main__":
    test_owner_epoch_can_read_memory_and_context()
    test_epoch_change_makes_old_memory_and_context_inaccessible()
    test_project_and_chat_walls_fail_closed()
    test_bound_repo_is_an_additional_wall()
    test_missing_epoch_fails_closed()
    test_normal_non_project_chat_not_broken_by_epoch_rules()
    print("PROJECT_MEMORY_EPOCH_CONTRACT_OK")
