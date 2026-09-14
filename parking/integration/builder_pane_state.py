from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
import json
import re
from typing import Mapping, Any

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_HANDLE = re.compile(r"^boh1\.[0-9a-f]{32}\.[0-9a-f]{32}$")
PANE_KINDS = ("file", "diff", "console", "test", "preview", "rollback")


class PaneStateError(ValueError):
    pass


class PaneAccessDenied(PermissionError):
    pass


def _id(name: str, value: str) -> str:
    if not isinstance(value, str) or not _ID.fullmatch(value) or "/" in value or "\\" in value:
        raise PaneStateError(f"invalid {name}")
    return value


def _scope_digest(chat_id: str, project_id: str, repo_scope: str) -> str:
    _id("chat_id", chat_id)
    _id("project_id", project_id)
    if not isinstance(repo_scope, str) or not repo_scope or len(repo_scope) > 1024:
        raise PaneStateError("invalid repo_scope")
    return hashlib.sha256(f"{chat_id}\0{project_id}\0{repo_scope}".encode()).hexdigest()


def _handles_digest(handles: Mapping[str, str | None]) -> str:
    if set(handles) != set(PANE_KINDS):
        raise PaneStateError("pane handles must contain the exact canonical kind set")
    normalized: dict[str, str | None] = {}
    for kind in PANE_KINDS:
        value = handles[kind]
        if value is not None and (not isinstance(value, str) or not _HANDLE.fullmatch(value)):
            raise PaneStateError(f"invalid {kind} handle")
        normalized[kind] = value
    body = json.dumps(normalized, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(body.encode()).hexdigest()


@dataclass(frozen=True)
class BuilderPaneState:
    """Secret-free authority for one interactive builder pane snapshot.

    Artifact bodies are never embedded. The state binds only opaque output handles to the
    exact Captain scope, Project State epoch, builder session and revision. The scope is
    stored as a digest so normal observability/UI projection cannot leak raw chat/project/
    repository identifiers.
    """

    version: int
    scope_digest: str
    epoch: int
    builder_session_id_hash: str
    revision: int
    handles_digest: str
    signature: str

    def public(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "scope_digest": self.scope_digest,
            "epoch": self.epoch,
            "builder_session_id_hash": self.builder_session_id_hash,
            "revision": self.revision,
            "handles_digest": self.handles_digest,
            "signature": self.signature,
        }


class BuilderPaneStateContract:
    VERSION = 1

    def __init__(self, secret: bytes):
        if not isinstance(secret, (bytes, bytearray)) or len(secret) < 32:
            raise PaneStateError("secret too short")
        self._secret = bytes(secret)

    def _signature(
        self,
        *,
        scope_digest: str,
        epoch: int,
        builder_session_id_hash: str,
        revision: int,
        handles_digest: str,
    ) -> str:
        body = json.dumps(
            {
                "version": self.VERSION,
                "scope_digest": scope_digest,
                "epoch": epoch,
                "builder_session_id_hash": builder_session_id_hash,
                "revision": revision,
                "handles_digest": handles_digest,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return hmac.new(self._secret, body, hashlib.sha256).hexdigest()

    def issue(
        self,
        *,
        chat_id: str,
        project_id: str,
        repo_scope: str,
        epoch: int,
        builder_session_id: str,
        revision: int,
        handles: Mapping[str, str | None],
    ) -> BuilderPaneState:
        if not isinstance(epoch, int) or isinstance(epoch, bool) or epoch < 0:
            raise PaneStateError("invalid epoch")
        if not isinstance(revision, int) or isinstance(revision, bool) or revision < 0:
            raise PaneStateError("invalid revision")
        sid = _id("builder_session_id", builder_session_id)
        scope = _scope_digest(chat_id, project_id, repo_scope)
        sid_hash = hashlib.sha256(sid.encode()).hexdigest()
        hdigest = _handles_digest(handles)
        sig = self._signature(
            scope_digest=scope,
            epoch=epoch,
            builder_session_id_hash=sid_hash,
            revision=revision,
            handles_digest=hdigest,
        )
        return BuilderPaneState(self.VERSION, scope, epoch, sid_hash, revision, hdigest, sig)

    def validate(
        self,
        state: BuilderPaneState | Mapping[str, Any],
        *,
        chat_id: str,
        project_id: str,
        repo_scope: str,
        current_epoch: int,
        builder_session_id: str,
        current_revision: int,
        handles: Mapping[str, str | None],
    ) -> dict[str, Any]:
        if isinstance(state, BuilderPaneState):
            raw = state.public()
        elif isinstance(state, Mapping):
            raw = dict(state)
        else:
            raise PaneAccessDenied("invalid pane state")

        expected_fields = {
            "version", "scope_digest", "epoch", "builder_session_id_hash",
            "revision", "handles_digest", "signature",
        }
        if set(raw) != expected_fields:
            raise PaneAccessDenied("pane state schema mismatch")
        if raw["version"] != self.VERSION:
            raise PaneAccessDenied("pane state version mismatch")
        if not isinstance(current_epoch, int) or isinstance(current_epoch, bool) or current_epoch < 0:
            raise PaneStateError("invalid current_epoch")
        if not isinstance(current_revision, int) or isinstance(current_revision, bool) or current_revision < 0:
            raise PaneStateError("invalid current_revision")

        scope = _scope_digest(chat_id, project_id, repo_scope)
        sid = _id("builder_session_id", builder_session_id)
        sid_hash = hashlib.sha256(sid.encode()).hexdigest()
        hdigest = _handles_digest(handles)
        expected_sig = self._signature(
            scope_digest=scope,
            epoch=current_epoch,
            builder_session_id_hash=sid_hash,
            revision=current_revision,
            handles_digest=hdigest,
        )
        checks = (
            hmac.compare_digest(str(raw["scope_digest"]), scope),
            raw["epoch"] == current_epoch,
            hmac.compare_digest(str(raw["builder_session_id_hash"]), sid_hash),
            raw["revision"] == current_revision,
            hmac.compare_digest(str(raw["handles_digest"]), hdigest),
            hmac.compare_digest(str(raw["signature"]), expected_sig),
        )
        if not all(checks):
            raise PaneAccessDenied("pane state scope/session/epoch/revision/handle mismatch")
        return dict(raw)
