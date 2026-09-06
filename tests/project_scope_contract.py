"""Shared fail-closed Project State scope contract used by Captain isolation regressions."""

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Scope:
    project_id: Optional[str] = None
    repo_scope: Optional[str] = None
    state_epoch: Optional[int] = None

    @property
    def is_normal(self) -> bool:
        return self.project_id is None and self.repo_scope is None and self.state_epoch is None

    @property
    def is_complete_project_scope(self) -> bool:
        valid_project_id = isinstance(self.project_id, str) and bool(self.project_id.strip())
        valid_repo_scope = isinstance(self.repo_scope, str) and bool(self.repo_scope.strip())
        valid_epoch = type(self.state_epoch) is int and self.state_epoch >= 0
        return valid_project_id and valid_repo_scope and valid_epoch

    def validate(self) -> None:
        if self.is_normal:
            return
        if not self.is_complete_project_scope:
            raise ValueError("partial or invalid project scope must fail closed")
