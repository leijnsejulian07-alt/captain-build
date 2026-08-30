from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Iterable, Sequence
import re

_PROFILE_RE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_ALLOWED_KINDS = {"build", "test", "lint", "typecheck", "format-check"}
_MAX_ARGS = 32
_MAX_ARG_CHARS = 512
_MAX_TIMEOUT_SECONDS = 900


class ProfileError(ValueError):
    pass


@dataclass(frozen=True)
class ScopedCommandProfile:
    profile_id: str
    kind: str
    executable: str
    args: tuple[str, ...]
    cwd_hash: str
    timeout_seconds: int


def _scope_hash(repo_scope: str) -> str:
    scope = str(repo_scope or "").strip()
    if not scope:
        raise ProfileError("repo_scope is required")
    return sha256(scope.encode("utf-8")).hexdigest()


def _inside_scope(repo_scope: str, cwd: str) -> bool:
    root = Path(repo_scope).expanduser().resolve(strict=False)
    child = Path(cwd).expanduser().resolve(strict=False)
    try:
        child.relative_to(root)
        return True
    except ValueError:
        return False


def compile_profile(
    *,
    profile_id: str,
    kind: str,
    executable: str,
    args: Sequence[str] | None,
    cwd: str,
    repo_scope: str,
    timeout_seconds: int = 300,
    allowed_executables: Iterable[str],
) -> ScopedCommandProfile:
    if not _PROFILE_RE.fullmatch(str(profile_id or "")):
        raise ProfileError("invalid profile_id")
    if kind not in _ALLOWED_KINDS:
        raise ProfileError("unknown command kind")

    exe = str(executable or "").strip()
    allow = {str(x).strip().lower() for x in allowed_executables if str(x).strip()}
    if not exe or exe.lower() not in allow:
        raise ProfileError("executable is not allowlisted")
    if any(ch in exe for ch in "\\/"):
        raise ProfileError("executable must be a bare allowlisted command name")

    argv = tuple(str(x) for x in (args or ()))
    if len(argv) > _MAX_ARGS:
        raise ProfileError("too many arguments")
    if any(len(x) > _MAX_ARG_CHARS for x in argv):
        raise ProfileError("argument too long")
    if any("\x00" in x or "\r" in x or "\n" in x for x in argv):
        raise ProfileError("control characters are not allowed in arguments")

    timeout = int(timeout_seconds)
    if timeout < 1 or timeout > _MAX_TIMEOUT_SECONDS:
        raise ProfileError("timeout out of bounds")
    if not _inside_scope(repo_scope, cwd):
        raise ProfileError("cwd escapes repo_scope")

    return ScopedCommandProfile(
        profile_id=profile_id,
        kind=kind,
        executable=exe,
        args=argv,
        cwd_hash=sha256(str(Path(cwd).expanduser().resolve(strict=False)).encode("utf-8")).hexdigest(),
        timeout_seconds=timeout,
    )


def materialize_for_execution(
    profile: ScopedCommandProfile,
    *,
    cwd: str,
    repo_scope: str,
) -> tuple[list[str], str, int]:
    if not _inside_scope(repo_scope, cwd):
        raise ProfileError("cwd escapes repo_scope")
    actual_hash = sha256(str(Path(cwd).expanduser().resolve(strict=False)).encode("utf-8")).hexdigest()
    if actual_hash != profile.cwd_hash:
        raise ProfileError("cwd does not match validated profile")
    _scope_hash(repo_scope)
    return [profile.executable, *profile.args], str(Path(cwd).expanduser().resolve(strict=False)), profile.timeout_seconds
