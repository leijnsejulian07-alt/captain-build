"""Captain-owned sandbox provider boundary.

Parking-only. Providers are execution subsystems, never a second control-plane.
All operations are bound to the exact Captain Project State wall.
"""
from dataclasses import dataclass
import hashlib
import json

_ALLOWED_ACTIONS = frozenset({"create", "resume", "snapshot", "exec", "preview", "diff", "destroy"})


def _text(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("non-empty string required")
    return value.strip()


@dataclass(frozen=True)
class SandboxScope:
    chat_id: str
    project_id: str
    repo_scope: str
    epoch: int
    builder_session_id: str

    def __post_init__(self) -> None:
        for name in ("chat_id", "project_id", "repo_scope", "builder_session_id"):
            object.__setattr__(self, name, _text(getattr(self, name)))
        if type(self.epoch) is not int or self.epoch < 0:
            raise ValueError("epoch must be a non-negative integer")

    def digest(self) -> str:
        payload = {
            "builder_session_id": self.builder_session_id,
            "chat_id": self.chat_id,
            "epoch": self.epoch,
            "project_id": self.project_id,
            "repo_scope": self.repo_scope,
        }
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True)
class SandboxRequest:
    provider_id: str
    action: str
    scope_digest: str

    @classmethod
    def issue(cls, provider_id: str, action: str, scope: SandboxScope) -> "SandboxRequest":
        provider_id = _text(provider_id)
        action = _text(action)
        if action not in _ALLOWED_ACTIONS:
            raise ValueError("unsupported sandbox action")
        return cls(provider_id=provider_id, action=action, scope_digest=scope.digest())

    def authorize(self, *, provider_id: str, action: str, current_scope: SandboxScope) -> bool:
        try:
            provider_id = _text(provider_id)
            action = _text(action)
        except ValueError:
            return False
        return (
            action in _ALLOWED_ACTIONS
            and self.provider_id == provider_id
            and self.action == action
            and len(self.scope_digest) == 64
            and self.scope_digest == current_scope.digest()
        )
