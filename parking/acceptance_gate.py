from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable, Mapping

_SHA = re.compile(r"^[0-9a-f]{40}$")
_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_REQUIRED_CHECKS = frozenset({"unit", "doctor", "router", "project_isolation", "repo_isolation"})
_ALLOWED_STATUS = frozenset({"pass", "fail", "blocked", "not_run"})


class PromotionBlocked(ValueError):
    pass


@dataclass(frozen=True)
class PromotionCandidate:
    candidate_id: str
    source_sha: str
    expected_local_base_sha: str
    dependencies: tuple[str, ...] = ()


def _stable_id(value: str, field: str) -> str:
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise PromotionBlocked(f"invalid {field}")
    return value


def _sha(value: str, field: str) -> str:
    if not isinstance(value, str) or not _SHA.fullmatch(value):
        raise PromotionBlocked(f"invalid {field}")
    return value


def validate_candidate(candidate: PromotionCandidate) -> PromotionCandidate:
    _stable_id(candidate.candidate_id, "candidate_id")
    _sha(candidate.source_sha, "source_sha")
    _sha(candidate.expected_local_base_sha, "expected_local_base_sha")
    if len(candidate.dependencies) > 32:
        raise PromotionBlocked("too many dependencies")
    seen: set[str] = set()
    for dep in candidate.dependencies:
        dep = _stable_id(dep, "dependency")
        if dep == candidate.candidate_id or dep in seen:
            raise PromotionBlocked("invalid dependency graph")
        seen.add(dep)
    return candidate


def can_promote(
    candidate: PromotionCandidate,
    *,
    actual_local_base_sha: str,
    checks: Mapping[str, str],
    integrated_dependencies: Iterable[str] = (),
) -> bool:
    validate_candidate(candidate)
    actual = _sha(actual_local_base_sha, "actual_local_base_sha")
    if actual != candidate.expected_local_base_sha:
        raise PromotionBlocked("local base moved")

    if not isinstance(checks, Mapping):
        raise PromotionBlocked("checks must be a mapping")
    unknown = set(checks) - _REQUIRED_CHECKS
    if unknown:
        raise PromotionBlocked("unknown acceptance check")
    missing = _REQUIRED_CHECKS - set(checks)
    if missing:
        raise PromotionBlocked("missing acceptance check")
    for name in _REQUIRED_CHECKS:
        status = checks[name]
        if status not in _ALLOWED_STATUS:
            raise PromotionBlocked(f"invalid status for {name}")
        if status != "pass":
            raise PromotionBlocked(f"acceptance check not green: {name}")

    integrated = {_stable_id(x, "integrated_dependency") for x in integrated_dependencies}
    missing_deps = set(candidate.dependencies) - integrated
    if missing_deps:
        raise PromotionBlocked("dependencies not integrated")
    return True


def public_gate_state(candidate: PromotionCandidate) -> dict[str, object]:
    validate_candidate(candidate)
    return {
        "candidate_id": candidate.candidate_id,
        "source_sha": candidate.source_sha,
        "expected_local_base_sha": candidate.expected_local_base_sha,
        "dependencies": list(candidate.dependencies),
        "required_checks": sorted(_REQUIRED_CHECKS),
        "policy": "fail-closed",
    }
