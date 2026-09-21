"""Parking regression for Captain Project Memory/context epoch isolation.
Pure contract test: no repo-authored commands or external code are executed.
"""


def project_record_visible(record, current):
    """Project records are readable only inside the exact current epoch wall."""
    if not isinstance(record, dict) or not isinstance(current, dict):
        return False
    if record.get("version") != 1 or record.get("kind") not in {"project_memory", "project_context"}:
        return False
    scope = record.get("scope")
    if not isinstance(scope, dict) or set(scope) - {"chat_id", "project_id", "repo_scope", "state_epoch"}:
        return False
    for key in ("chat_id", "project_id"):
        value = scope.get(key)
        if not isinstance(value, str) or not value or value != current.get(key):
            return False
    epoch = scope.get("state_epoch")
    if not isinstance(epoch, int) or isinstance(epoch, bool) or epoch < 0 or epoch != current.get("state_epoch"):
        return False
    bound_repo = scope.get("repo_scope")
    if bound_repo is not None:
        if not isinstance(bound_repo, str) or not bound_repo or bound_repo != current.get("repo_scope"):
            return False
    return isinstance(record.get("payload"), dict)


def normal_chat_record_visible(record, current):
    """Non-project chat remains independent of Project State epochs."""
    if not isinstance(record, dict) or not isinstance(current, dict) or current.get("project_id") is not None:
        return False
    return record.get("kind") == "chat_memory" and record.get("chat_id") == current.get("chat_id")


def fixture(kind="project_memory", repo_scope="repo-a"):
    record = {"version": 1, "scope": {"chat_id": "chat-a", "project_id": "project-a", "repo_scope": repo_scope,
              "state_epoch": 9}, "kind": kind, "created_at": "2026-09-21T04:00:00Z", "payload": {"summary": "scoped"}}
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


def test_project_chat_and_repo_walls_fail_closed():
    for key in ("chat_id", "project_id"):
        record, current = fixture(); current[key] += "-other"
        assert not project_record_visible(record, current), key
    record, current = fixture(); current["repo_scope"] = "repo-b"
    assert not project_record_visible(record, current)


def test_unbound_repo_remains_project_scoped():
    record, current = fixture(repo_scope=None); current["repo_scope"] = "repo-b"
    assert project_record_visible(record, current)


def test_malformed_scope_fails_closed():
    mutations = [
        lambda s: s.pop("state_epoch"), lambda s: s.__setitem__("state_epoch", True),
        lambda s: s.__setitem__("state_epoch", -1), lambda s: s.__setitem__("chat_id", ""),
        lambda s: s.__setitem__("project_id", None), lambda s: s.__setitem__("repo_scope", ""),
        lambda s: s.__setitem__("unexpected", "x"),
    ]
    for mutate in mutations:
        record, current = fixture(); mutate(record["scope"])
        assert not project_record_visible(record, current)


def test_normal_non_project_chat_not_broken_by_epoch_rules():
    record = {"kind": "chat_memory", "chat_id": "chat-normal", "payload": {"summary": "hello"}}
    assert normal_chat_record_visible(record, {"chat_id": "chat-normal", "project_id": None})
    assert not normal_chat_record_visible(record, {"chat_id": "chat-other", "project_id": None})
    assert not normal_chat_record_visible(record, {"chat_id": "chat-normal", "project_id": "project-a", "state_epoch": 9})


if __name__ == "__main__":
    test_owner_epoch_can_read_memory_and_context(); test_epoch_change_makes_old_memory_and_context_inaccessible()
    test_project_chat_and_repo_walls_fail_closed(); test_unbound_repo_remains_project_scoped()
    test_malformed_scope_fails_closed(); test_normal_non_project_chat_not_broken_by_epoch_rules()
    print("PROJECT_MEMORY_EPOCH_CONTRACT_OK")
