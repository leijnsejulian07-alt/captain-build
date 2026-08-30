from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable
import re

_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_KINDS = {"connector", "skill", "builder", "research", "browser", "memory", "eval", "tool"}
_AUTH = {"none", "oauth", "api-key", "id", "local"}

@dataclass(frozen=True)
class PluginManifest:
    plugin_id: str
    name: str
    kind: str
    auth_method: str
    installed: bool
    connected: bool
    enabled: bool
    permissions: tuple[str, ...]
    required_permissions: tuple[str, ...]
    version: str | None = None
    setup_version: int = 1
    verified_setup_version: int | None = None
    health: str = "unknown"

    def validate(self) -> None:
        if not _ID.fullmatch(self.plugin_id):
            raise ValueError("invalid plugin_id")
        if not self.name or len(self.name) > 96:
            raise ValueError("invalid name")
        if self.kind not in _KINDS or self.auth_method not in _AUTH:
            raise ValueError("unsupported manifest kind/auth")
        if self.setup_version < 1 or isinstance(self.setup_version, bool):
            raise ValueError("invalid setup_version")
        if self.connected and not self.installed:
            raise ValueError("connected plugin must be installed")
        if self.enabled and not self.installed:
            raise ValueError("enabled plugin must be installed")
        perms = set(self.permissions)
        req = set(self.required_permissions)
        if len(perms) != len(self.permissions) or len(req) != len(self.required_permissions):
            raise ValueError("duplicate permission")
        for p in perms | req:
            if not _ID.fullmatch(p):
                raise ValueError("invalid permission")
        if not req <= perms:
            raise ValueError("required permission missing from declared permissions")

    @property
    def ready(self) -> bool:
        self.validate()
        healthy = self.health in {"ok", "healthy"}
        setup_ok = self.verified_setup_version == self.setup_version
        auth_ok = self.auth_method in {"none", "local"} or self.connected
        return self.installed and self.enabled and auth_ok and healthy and setup_ok

    def public_state(self) -> dict:
        self.validate()
        return {
            "id": self.plugin_id,
            "name": self.name,
            "kind": self.kind,
            "auth_method": self.auth_method,
            "installed": self.installed,
            "connected": self.connected,
            "enabled": self.enabled,
            "ready": self.ready,
            "permissions": list(self.permissions),
            "required_permissions": list(self.required_permissions),
            "version": self.version,
            "setup_version": self.setup_version,
            "verified_setup_version": self.verified_setup_version,
            "health": self.health,
            "settings_anchor": f"plugin-{self.plugin_id}",
        }


def build_registry(manifests: Iterable[PluginManifest]) -> list[dict]:
    seen: set[str] = set()
    out: list[dict] = []
    for manifest in manifests:
        manifest.validate()
        if manifest.plugin_id in seen:
            raise ValueError("duplicate plugin_id")
        seen.add(manifest.plugin_id)
        out.append(manifest.public_state())
    return sorted(out, key=lambda x: (x["kind"], x["name"].lower(), x["id"]))
