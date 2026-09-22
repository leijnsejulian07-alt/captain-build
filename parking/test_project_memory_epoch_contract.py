"""Parking regressions for Captain Project Memory/context epoch isolation.
Pure contract tests: no repo-authored commands or external code are executed.
"""


def project_record_visible(record, current):
    """Project records are readable only inside the exact current epoch wall."""
    if not isinstance(record, dict) or not isinstance(current, dict):
        return False
    if record.get("version") != 1 or record.get("kind") not in {"project_memory", "project_context"}:
        return False
    scope = record.get("scope")
    required = {"chat_id", "project_id", "repo_scope_hash", "state_epoch"}
    if not isinstance(scope, dict) or set(scope) != required:
        return False
    for key in ("chat_id", "project_id", "repo_scope_hash"):
        value = scope.get(key)
        if not isinstance(value, str) or not value or value != current.get(key):
            return False
    epoch = scope.get("state_epoch")
    if not isinstance(epoch, int) or isinstance(epoch, bool) or epoch < 1 or epoch != current.get("state_epoch"):
        return False
    return isinstance(record.get("payload"), dict)


def normal_chat_record_visible(record, current):
    """Non-project chat remains independent of Project State epochs."""
    if not isinstance(record, dict) or not isinstance(current, dict) or current.get("project_id") is not None:
        return False
    return record.get("kind") == "chat_memory" and record.get("chat_id") == current.get("chat_id")


def fixture(kind="project_memory"):
    scope = {"chat_id": "chat-a", "project_id": "project-a", "repo_scope_hash": "0123456789abcdef", "state_epoch": 9}
    record = {"version": 1, "scope": dict(scope), "kind": kind,
              "created_at": "2026-09-22T19:00:00+02:00", "payload": {"summary": "scoped"}}
    return record, dict(scope)


def test_owner_epoch_can_read_memory_and_context():
    for kind in ("project_memory", "project_context"):
        record, current = fixture(kind)
        assert project_record_visible(record, current)


def test_epoch_change_makes_old_memory_and_context_inaccessible():
    for kind in ("project_memory", "project_context"):
        record, current = fixture(kind); current["state_epoch"] += 1
        assert not project_record_visible(record, current)


def test_every_authority_wall_fails_closed():
    for key, bad in (("chat_id", "chat-b"), ("project_id", "project-b"),
                     ("repo_scope_hash", "fedcba9876543210"), ("state_epoch", 10)):
        record, current = fixture(); record["scope"][key] = bad
        assert not project_record_visible(record, current), key


def test_missing_or_malformed_scope_fails_closed():
    mutations = [
        lambda s: s.pop("state_epoch"), lambda s: s.__setitem__("state_epoch", True),
        lambda s: s.__setitem__("state_epoch", 0), lambda s: s.__setitem__("state_epoch", -1),
        lambda s: s.__setitem__("chat_id", ""), lambda s: s.__setitem__("project_id", None),
        lambda s: s.__setitem__("repo_scope_hash", ""), lambda s: s.__setitem__("unexpected", "x"),
    ]
    for mutate in mutations:
        record, current = fixture(); mutate(record["scope"])
        assert not project_record_visible(record, current)


def test_raw_or_unbound_repo_scope_is_never_accepted():
    record, current = fixture(); record["scope"].pop("repo_scope_hash"); record["scope"]["repo_scope"] = "C:/repo"
    assert not project_record_visible(record, current)
    record, current = fixture(); record["scope"]["repo_scope_hash"] = None
    assert not project_record_visible(record, current)


def test_normal_non_project_chat_not_broken_by_epoch_rules():
    record = {"kind": "chat_memory", "chat_id": "chat-normal", "payload": {"summary": "hello"}}
    assert normal_chat_record_visible(record, {"chat_id": "chat-normal", "project_id": None})
    assert not normal_chat_record_visible(record, {"chat_id": "chat-other", "project_id": None})
    assert not normal_chat_record_visible(record, {"chat_id": "chat-normal", "project_id": "project-a", "state_epoch": 9})


if __name__ == "__main__":
    test_owner_epoch_can_read_memory_and_context(); test_epoch_change_makes_old_memory_and_context_inaccessible()
    test_every_authority_wall_fails_closed(); test_missing_or_malformed_scope_fails_closed()
    test_raw_or_unbound_repo_scope_is_never_accepted(); test_normal_non_project_chat_not_broken_by_epoch_rules()
    print("PROJECT_MEMORY_EPOCH_CONTRACT_OK")
