"""Hostile-input parking regression for Captain builder resume-delta.
No repository-authored commands are executed. Reconcile locally only after runtime review.
"""
from copy import deepcopy
from pathlib import PurePosixPath

WALLS = ("chat_id", "project_id", "repo_scope", "builder_session_id", "state_epoch")
MAX_CHANGED_PATHS = 500
MAX_PATH_CHARS = 1024


def safe_repo_relative_path(value):
    if not isinstance(value, str) or not value or len(value) > MAX_PATH_CHARS or "\x00" in value:
        return False
    # Resume metadata must describe repository-relative POSIX paths only.
    # Reject absolute, parent traversal, Windows separators/drive-like paths,
    # and ambiguous empty/dot segments before any local filesystem use.
    if "\\" in value or value.startswith("/"):
        return False
    parts = value.split("/")
    if any(part in ("", ".", "..") for part in parts):
        return False
    path = PurePosixPath(value)
    return not path.is_absolute() and ".." not in path.parts


def resume_delta_usable(saved, current):
    if not isinstance(saved, dict) or not isinstance(current, dict):
        return False
    if saved.get("version") != 1:
        return False
    scope = saved.get("scope")
    if not isinstance(scope, dict):
        return False
    for key in WALLS:
        if key not in scope or key not in current or scope[key] != current[key]:
            return False
    observed = saved.get("observed")
    if not isinstance(observed, dict):
        return False
    head = observed.get("head")
    if not isinstance(head, str) or not head or head != current.get("head"):
        return False
    delta = saved.get("delta")
    if not isinstance(delta, dict):
        return False
    paths = delta.get("changed_paths")
    if not isinstance(paths, list) or len(paths) > MAX_CHANGED_PATHS:
        return False
    if any(not safe_repo_relative_path(p) for p in paths):
        return False
    hashes = delta.get("manifest_hashes")
    if not isinstance(hashes, dict):
        return False
    freshness = saved.get("freshness")
    if not isinstance(freshness, dict):
        return False
    return all(freshness.get(k) is True for k in ("scope_match", "epoch_match", "head_match", "usable"))


def fixture():
    scope = {"chat_id":"c","project_id":"p","repo_scope":"r","builder_session_id":"s","state_epoch":1}
    saved = {"version":1,"scope":deepcopy(scope),"observed":{"head":"abc","base":"def"},"delta":{"changed_paths":["src/app.py"],"manifest_hashes":{}},"freshness":{"scope_match":True,"epoch_match":True,"head_match":True,"usable":True}}
    return saved, {**scope,"head":"abc"}


def reject(mutator):
    saved, current = fixture(); mutator(saved, current); assert not resume_delta_usable(saved, current)


def test_owner():
    saved, current = fixture(); assert resume_delta_usable(saved, current)


def test_hostile_inputs_fail_closed():
    cases = [
        lambda s,c: s.update(version=2),
        lambda s,c: s.update(scope=None),
        lambda s,c: s["scope"].pop("state_epoch"),
        lambda s,c: c.pop("builder_session_id"),
        lambda s,c: s.update(observed={"head":""}),
        lambda s,c: c.update(head="moved"),
        lambda s,c: s.update(delta=None),
        lambda s,c: s["delta"].update(changed_paths="src/app.py"),
        lambda s,c: s["delta"].update(changed_paths=["x"]*(MAX_CHANGED_PATHS+1)),
        lambda s,c: s["delta"].update(changed_paths=["a\x00b"]),
        lambda s,c: s["delta"].update(changed_paths=["x"*(MAX_PATH_CHARS+1)]),
        lambda s,c: s["delta"].update(changed_paths=["../secrets.txt"]),
        lambda s,c: s["delta"].update(changed_paths=["src/../../secrets.txt"]),
        lambda s,c: s["delta"].update(changed_paths=["/etc/passwd"]),
        lambda s,c: s["delta"].update(changed_paths=["src\\app.py"]),
        lambda s,c: s["delta"].update(changed_paths=["C:\\temp\\x"]),
        lambda s,c: s["delta"].update(changed_paths=["src//app.py"]),
        lambda s,c: s["delta"].update(changed_paths=["./src/app.py"]),
        lambda s,c: s["delta"].update(manifest_hashes=[]),
        lambda s,c: s.update(freshness={"scope_match":True,"epoch_match":True,"head_match":True,"usable":False}),
    ]
    for case in cases: reject(case)


if __name__ == "__main__":
    test_owner(); test_hostile_inputs_fail_closed(); print("BUILDER_RESUME_DELTA_HOSTILE_CONTRACT_OK")
