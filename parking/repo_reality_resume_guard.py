"""Captain parking implementation: repo reality/resume guard.

Pure validation only: no filesystem access, subprocesses, repo commands, or provider calls.
Reconcile into Captain/OpenBuilder only after local runtime review.
"""
import re
from pathlib import PurePosixPath

WALLS = ("chat_id", "project_id", "repo_scope", "builder_session_id", "state_epoch")
MAX_LABEL = 256
MAX_CHANGED_PATHS = 500
MAX_PATH_CHARS = 1024
MAX_MANIFESTS = 32
MAX_SYMBOLS = 1000
MAX_SYMBOL_CHARS = 512
_SHA = re.compile(r"^[0-9a-f]{7,64}$")
_HASH = re.compile(r"^[0-9a-f]{64}$")


def _plain_label(value):
    return type(value) is str and 0 < len(value) <= MAX_LABEL


def _safe_path(value):
    if type(value) is not str or not value or len(value) > MAX_PATH_CHARS or "\x00" in value:
        return False
    if "\\" in value or value.startswith("/") or re.match(r"^[A-Za-z]:", value):
        return False
    parts = value.split("/")
    if any(part in ("", ".", "..") for part in parts):
        return False
    path = PurePosixPath(value)
    return not path.is_absolute() and ".." not in path.parts


def resume_delta_usable(saved, current):
    """Return True only for an inert, bounded delta owned by current exact authority."""
    if type(saved) is not dict or type(current) is not dict or saved.get("version") != 1:
        return False

    scope = saved.get("scope")
    if type(scope) is not dict or set(scope) != set(WALLS):
        return False
    for key in WALLS[:-1]:
        if not _plain_label(scope.get(key)) or not _plain_label(current.get(key)):
            return False
        if scope[key] != current[key]:
            return False
    epoch = scope.get("state_epoch")
    current_epoch = current.get("state_epoch")
    if type(epoch) is not int or epoch < 0 or type(current_epoch) is not int or current_epoch < 0 or epoch != current_epoch:
        return False

    observed = saved.get("observed")
    if type(observed) is not dict or set(observed) != {"head", "base", "generated_at"}:
        return False
    head, base = observed.get("head"), observed.get("base")
    if type(head) is not str or type(base) is not str or not _SHA.fullmatch(head) or not _SHA.fullmatch(base):
        return False
    current_head = current.get("head")
    if type(current_head) is not str or not _SHA.fullmatch(current_head) or head != current_head:
        return False
    if type(observed.get("generated_at")) is not str or not observed["generated_at"]:
        return False

    delta = saved.get("delta")
    if type(delta) is not dict or not {"changed_paths", "manifest_hashes"}.issubset(delta) or not set(delta) <= {"changed_paths", "manifest_hashes", "symbol_delta"}:
        return False
    paths = delta.get("changed_paths")
    if type(paths) is not list or len(paths) > MAX_CHANGED_PATHS:
        return False
    if any(not _safe_path(p) for p in paths) or len(set(paths)) != len(paths):
        return False

    manifests = delta.get("manifest_hashes")
    if type(manifests) is not dict or len(manifests) > MAX_MANIFESTS:
        return False
    for path, digest in manifests.items():
        if not _safe_path(path) or type(digest) is not str or not _HASH.fullmatch(digest):
            return False

    symbols = delta.get("symbol_delta", [])
    if type(symbols) is not list or len(symbols) > MAX_SYMBOLS:
        return False
    if any(type(s) is not str or len(s) > MAX_SYMBOL_CHARS for s in symbols):
        return False

    freshness = saved.get("freshness")
    if type(freshness) is not dict or set(freshness) != {"scope_match", "epoch_match", "head_match", "usable"}:
        return False
    return all(type(freshness[k]) is bool and freshness[k] is True for k in freshness)
