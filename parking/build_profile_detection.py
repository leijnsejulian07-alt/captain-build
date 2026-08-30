"""Fail-closed repo build-profile detection for Captain parking work.

Detection is metadata-only: it never executes repository scripts or commands.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Iterable, Mapping

MAX_FILES = 4096
MAX_PATH = 240

@dataclass(frozen=True)
class ProfileHint:
    ecosystem: str
    profile_ids: tuple[str, ...]
    confidence: str
    evidence: tuple[str, ...]

_ALLOWED_FILES = {
    "package.json", "package-lock.json", "pnpm-lock.yaml", "yarn.lock",
    "pyproject.toml", "pytest.ini", "requirements.txt", "poetry.lock",
    "Cargo.toml", "Cargo.lock", "go.mod", "go.sum",
}


def _normalize(paths: Iterable[str]) -> set[str]:
    items = list(paths)
    if len(items) > MAX_FILES:
        raise ValueError("too many repository paths")
    out: set[str] = set()
    for raw in items:
        if not isinstance(raw, str) or not raw or len(raw) > MAX_PATH or "\x00" in raw:
            raise ValueError("invalid repository path")
        path = PurePosixPath(raw.replace("\\", "/"))
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("unsafe repository path")
        name = path.name
        if name in _ALLOWED_FILES:
            out.add(name)
    return out


def detect_build_profiles(paths: Iterable[str], metadata: Mapping[str, object] | None = None) -> tuple[ProfileHint, ...]:
    """Return conservative profile hints without trusting repo-defined commands."""
    files = _normalize(paths)
    metadata = metadata or {}
    if not isinstance(metadata, Mapping):
        raise ValueError("metadata must be a mapping")
    hints: list[ProfileHint] = []
    if "package.json" in files:
        lock = next((x for x in ("pnpm-lock.yaml", "package-lock.json", "yarn.lock") if x in files), None)
        evidence = ("package.json",) + ((lock,) if lock else ())
        hints.append(ProfileHint("node", ("node:typecheck", "node:test", "node:build"), "high" if lock else "medium", evidence))
    if "pyproject.toml" in files or "pytest.ini" in files:
        evidence = tuple(x for x in ("pyproject.toml", "pytest.ini") if x in files)
        hints.append(ProfileHint("python", ("python:pytest",), "high" if "pytest.ini" in files else "medium", evidence))
    if "Cargo.toml" in files:
        hints.append(ProfileHint("rust", ("rust:check", "rust:test"), "medium", ("Cargo.toml",)))
    if "go.mod" in files:
        hints.append(ProfileHint("go", ("go:test",), "medium", ("go.mod",)))
    return tuple(sorted(hints, key=lambda h: h.ecosystem))
