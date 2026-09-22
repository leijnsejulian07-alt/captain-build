from __future__ import annotations

from dataclasses import dataclass, replace
from hashlib import sha256
import re

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
STAGES = ("plan", "build", "test", "review", "debug", "done", "failed")
TERMINAL = {"done", "failed"}
NEXT = {
    "plan": {"build", "failed"},
    "build": {"test", "failed"},
    "test": {"review", "debug", "failed"},
    "review": {"done", "debug", "failed"},
    "debug": {"build", "test", "failed"},
}


def _valid_id(value: str) -> bool:
    return isinstance(value, str) and bool(_ID.fullmatch(value))


def _scope_hash(repo_scope: str) -> str:
    if not isinstance(repo_scope, str) or not repo_scope.strip():
        raise ValueError("repo_scope required")
    return sha256(repo_scope.strip().encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class RepoAgentLoop:
    loop_id: str
    chat_id: str
    project_id: str
    repo_scope_hash: str
    stage: str = "plan"
    revision: int = 0
    debug_cycles: int = 0
    max_debug_cycles: int = 3

    @classmethod
    def create(cls, *, loop_id: str, chat_id: str, project_id: str, repo_scope: str, max_debug_cycles: int = 3):
        for name, value in (("loop_id", loop_id), ("chat_id", chat_id), ("project_id", project_id)):
            if not _valid_id(value):
                raise ValueError(f"invalid {name}")
        if isinstance(max_debug_cycles, bool) or not isinstance(max_debug_cycles, int) or not 0 <= max_debug_cycles <= 10:
            raise ValueError("invalid max_debug_cycles")
        return cls(loop_id, chat_id, project_id, _scope_hash(repo_scope), max_debug_cycles=max_debug_cycles)

    def assert_scope(self, *, chat_id: str, project_id: str, repo_scope: str) -> None:
        if chat_id != self.chat_id or project_id != self.project_id or _scope_hash(repo_scope) != self.repo_scope_hash:
            raise PermissionError("scope mismatch")

    def advance(self, target: str, *, chat_id: str, project_id: str, repo_scope: str):
        self.assert_scope(chat_id=chat_id, project_id=project_id, repo_scope=repo_scope)
        if self.stage in TERMINAL:
            raise ValueError("terminal loop")
        if target not in STAGES or target not in NEXT[self.stage]:
            raise ValueError("invalid transition")
        debug_cycles = self.debug_cycles
        if target == "debug":
            debug_cycles += 1
            if debug_cycles > self.max_debug_cycles:
                raise ValueError("debug budget exhausted")
        return replace(self, stage=target, revision=self.revision + 1, debug_cycles=debug_cycles)

    def public_state(self) -> dict:
        return {
            "loop_id": self.loop_id,
            "repo_scope_hash": self.repo_scope_hash,
            "stage": self.stage,
            "revision": self.revision,
            "debug_cycles": self.debug_cycles,
            "max_debug_cycles": self.max_debug_cycles,
        }
