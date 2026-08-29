from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Iterable

BLOCKED_PATTERNS = (
    "ignore previous instructions",
    "bypass authentication",
    "disable authorization",
    "reveal secrets",
    "print environment variables",
    "exfiltrate",
)

ALLOWED_SCOPES = {"global", "project"}


class SkillValidationError(ValueError):
    pass


@dataclass(frozen=True)
class SkillMetadata:
    id: str
    name: str
    description: str
    scope: str
    permissions: tuple[str, ...]
    content_hash: str
    source_path: str


def _parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    if not text.startswith("---\n"):
        raise SkillValidationError("SKILL.md must start with YAML-like frontmatter")
    end = text.find("\n---\n", 4)
    if end < 0:
        raise SkillValidationError("frontmatter is not terminated")
    raw = text[4:end]
    body = text[end + 5 :]
    meta: dict[str, str] = {}
    for line in raw.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if ":" not in line:
            raise SkillValidationError(f"invalid frontmatter line: {line!r}")
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if not key or key in meta:
            raise SkillValidationError(f"invalid or duplicate field: {key!r}")
        meta[key] = value
    return meta, body


def _permissions(value: str) -> tuple[str, ...]:
    if not value:
        return ()
    return tuple(sorted({p.strip() for p in value.split(",") if p.strip()}))


def _contains_blocked_instruction(body: str) -> str | None:
    low = body.casefold()
    for pattern in BLOCKED_PATTERNS:
        if pattern in low:
            return pattern
    return None


def validate_skill(
    path: str | Path,
    *,
    chat_id: str,
    project_id: str,
    repo_scope: str,
    granted_permissions: Iterable[str] = (),
    enabled: bool = True,
) -> SkillMetadata:
    """Validate one SKILL.md without executing any skill content.

    Fail-closed invariants:
    - chat_id, project_id and repo_scope are always required.
    - project-scoped skills must physically reside within repo_scope.
    - declared permissions must already be granted.
    - suspicious auth/secret-bypass instructions are rejected.
    """
    if not enabled:
        raise SkillValidationError("skill is disabled")
    if not all((chat_id.strip(), project_id.strip(), repo_scope.strip())):
        raise SkillValidationError("chat_id, project_id and repo_scope are required")

    p = Path(path).expanduser().resolve()
    repo = Path(repo_scope).expanduser().resolve()
    if p.name.lower() != "skill.md":
        raise SkillValidationError("skill entrypoint must be named SKILL.md")
    if not p.is_file():
        raise SkillValidationError("skill file does not exist")

    raw = p.read_text(encoding="utf-8")
    meta, body = _parse_frontmatter(raw)
    required = ("id", "name", "description", "scope")
    missing = [k for k in required if not meta.get(k, "").strip()]
    if missing:
        raise SkillValidationError("missing required fields: " + ", ".join(missing))

    scope = meta["scope"].casefold()
    if scope not in ALLOWED_SCOPES:
        raise SkillValidationError(f"unsupported scope: {scope}")
    if scope == "project":
        try:
            p.relative_to(repo)
        except ValueError as exc:
            raise SkillValidationError("project skill escapes active repo_scope") from exc

    declared = _permissions(meta.get("permissions", ""))
    granted = {x.strip() for x in granted_permissions if x.strip()}
    missing_permissions = [perm for perm in declared if perm not in granted]
    if missing_permissions:
        raise SkillValidationError(
            "missing granted permissions: " + ", ".join(missing_permissions)
        )

    blocked = _contains_blocked_instruction(body)
    if blocked:
        raise SkillValidationError(f"blocked instruction pattern detected: {blocked}")

    return SkillMetadata(
        id=meta["id"].strip(),
        name=meta["name"].strip(),
        description=meta["description"].strip(),
        scope=scope,
        permissions=declared,
        content_hash=sha256(raw.encode("utf-8")).hexdigest(),
        source_path=str(p),
    )
