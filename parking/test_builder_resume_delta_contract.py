"""Parking regression for Captain builder resume-delta scope/freshness semantics.
No repo-authored commands are executed. Reconcile into local Captain only after runtime review.
"""
from copy import deepcopy

WALLS = ("chat_id", "project_id", "repo_scope", "builder_session_id", "state_epoch")


def resume_delta_usable(saved, current):
    """Fail closed: exact five-wall scope + current HEAD are mandatory."""
    if not isinstance(saved, dict) or not isinstance(current, dict):
        return False
    scope = saved.get("scope")
    if not isinstance(scope, dict):
        return False
    if any(scope.get(k) != current.get(k) for k in WALLS):
        return False
    observed = saved.get("observed")
    if not isinstance(observed, dict) or not observed.get("head"):
        return False
    if observed["head"] != current.get("head"):
        return False
    freshness = saved.get("freshness")
    if not isinstance(freshness, dict):
        return False
    return all(freshness.get(k) is True for k in ("scope_match", "epoch_match", "head_match", "usable"))


def fixture():
    scope = {
        "chat_id": "chat-a",
        "project_id": "project-a",
        "repo_scope": "repo-a",
        "builder_session_id": "session-a",
        "state_epoch": 7,
    }
    saved = {
        "version": 1,
        "scope": deepcopy(scope),
        "observed": {"head": "abcdef1", "base": "1234567", "generated_at": "2026-09-21T00:00:00Z"},
        "delta": {"changed_paths": ["src/app.py"], "manifest_hashes": {}},
        "freshness": {"scope_match": True, "epoch_match": True, "head_match": True, "usable": True},
    }
    current = {**scope, "head": "abcdef1"}
    return saved, current


def test_owner_can_resume():
    saved, current = fixture()
    assert resume_delta_usable(saved, current)


def test_each_wall_fails_closed():
    for wall in WALLS:
        saved, current = fixture()
        current[wall] = current[wall] + "-other" if isinstance(current[wall], str) else current[wall] + 1
        assert not resume_delta_usable(saved, current), wall


def test_head_change_requires_revalidation():
    saved, current = fixture()
    current["head"] = "fedcba9"
    assert not resume_delta_usable(saved, current)


def test_missing_scope_or_freshness_fails_closed():
    saved, current = fixture()
    del saved["scope"]["state_epoch"]
    assert not resume_delta_usable(saved, current)
    saved, current = fixture()
    saved["freshness"]["usable"] = False
    assert not resume_delta_usable(saved, current)


if __name__ == "__main__":
    test_owner_can_resume()
    test_each_wall_fails_closed()
    test_head_change_requires_revalidation()
    test_missing_scope_or_freshness_fails_closed()
    print("BUILDER_RESUME_DELTA_CONTRACT_OK")
