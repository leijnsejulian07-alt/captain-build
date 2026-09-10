"""Canonical fail-closed authority checks for Captain project-scoped state.

This module is intentionally provider/framework independent so Project Memory,
context, jobs, builder resources, connectors and update streams can share one
ownership predicate without creating a second control-plane.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


class AuthorityError(ValueError):
    """Raised when a project scope is partial, malformed, or unauthorized."""


@dataclass(frozen=True)
class ProjectAuthority:
    chat_id: Optional[str] = None
    project_id: Optional[str] = None
    repo_scope: Optional[str] = None
    state_epoch: Optional[int] = None

    @property
    def is_normal_chat(self) -> bool:
        return (
            self.chat_id is None
            and self.project_id is None
            and self.repo_scope is None
            and self.state_epoch is None
        )

    @property
    def is_project_scope(self) -> bool:
        return not self.is_normal_chat

    def validate(self) -> "ProjectAuthority":
        if self.is_normal_chat:
            return self

        if not all(
            isinstance(value, str) and bool(value.strip())
            for value in (self.chat_id, self.project_id, self.repo_scope)
        ):
            raise AuthorityError("partial or invalid project authority must fail closed")

        if type(self.state_epoch) is not int or self.state_epoch < 0:
            raise AuthorityError("state_epoch must be a non-negative integer")

        return self

    def same_owner(self, other: "ProjectAuthority") -> bool:
        """Return True only for identical validated ownership + epoch.

        Normal chat is intentionally compatible only with normal chat. Project
        authority never degrades into a partial/global scope.
        """
        self.validate()
        other.validate()
        if self.is_normal_chat or other.is_normal_chat:
            return self.is_normal_chat and other.is_normal_chat
        return self == other

    def require_same_owner(self, other: "ProjectAuthority") -> None:
        if not self.same_owner(other):
            raise AuthorityError("project authority mismatch")


@dataclass(frozen=True)
class ScopedRecord:
    """Minimal authority envelope for persisted Captain state."""

    authority: ProjectAuthority
    generic: bool = False
    project_specific: bool = True

    def readable_by(self, request: ProjectAuthority) -> bool:
        """Fail-closed read predicate used by memory/context-style stores.

        Raw project state never crosses an authority wall. Explicitly global,
        distilled, non-project-specific learning may be consumed from a project.
        Project-specific global records are denied to projects as a safety belt.
        """
        self.authority.validate()
        request.validate()

        if request.is_normal_chat:
            return self.authority.is_normal_chat

        if self.authority.is_normal_chat:
            return self.generic and not self.project_specific

        return self.authority.same_owner(request)


def require_current_epoch(
    authority: ProjectAuthority,
    *,
    current_epoch: int,
) -> None:
    """Reject stale/future project state against the active Project State epoch."""
    authority.validate()
    if authority.is_normal_chat:
        return
    if type(current_epoch) is not int or current_epoch < 0:
        raise AuthorityError("current_epoch must be a non-negative integer")
    if authority.state_epoch != current_epoch:
        raise AuthorityError("stale or future project authority epoch")
