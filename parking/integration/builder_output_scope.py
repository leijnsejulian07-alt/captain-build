from __future__ import annotations

import hashlib
import json
import re
from typing import Mapping

from parking.integration.builder_session_contract import authorize_builder_action

SCHEMA_VERSION = 1
MAX_REVISION = 2**63 - 1
_OUTPUT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,191}$")
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_ALLOWED_KINDS = frozenset({"console", "diff", "file", "preview"})
_KIND_CAPABILITY = {
    "console": "console_read",
    "diff": "diff_read",
    "file": "file_read",
    "preview": "preview_open",
}


def _digest(payload: Mapping[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def issue_builder_output(
    *,
    session: Mapping[str, object],
    output_id: str,
    kind: str,
    revision: int,
    content_digest: str,
) -> dict[str, object]:
    """Create a metadata-only handle for an interactive builder output.

    The handle deliberately stores no output body, path, prompt or repository scope. It
    is cryptographically bound to the already-scoped builder session and therefore to
    chat/project/repo/state-epoch/worktree authority.
    """
    if not isinstance(session, Mapping):
        raise ValueError("invalid builder session")
    binding = session.get("binding_digest")
    state_epoch = session.get("state_epoch")
    if not isinstance(binding, str) or not _DIGEST_RE.fullmatch(binding):
        raise ValueError("invalid builder session binding")
    if isinstance(state_epoch, bool) or not isinstance(state_epoch, int) or state_epoch < 1:
        raise ValueError("invalid builder state epoch")
    if not isinstance(output_id, str) or not _OUTPUT_ID_RE.fullmatch(output_id):
        raise ValueError("invalid output_id")
    if kind not in _ALLOWED_KINDS:
        raise ValueError("invalid output kind")
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1 or revision > MAX_REVISION:
        raise ValueError("invalid output revision")
    if not isinstance(content_digest, str) or not _DIGEST_RE.fullmatch(content_digest):
        raise ValueError("invalid content_digest")

    payload = {
        "schema_version": SCHEMA_VERSION,
        "session_binding_digest": binding,
        "state_epoch": state_epoch,
        "output_id": output_id,
        "kind": kind,
        "revision": revision,
        "content_digest": content_digest,
    }
    return {**payload, "output_binding_digest": _digest(payload)}


def authorize_builder_output(
    output: Mapping[str, object],
    *,
    session: Mapping[str, object],
    chat_id: str,
    project_id: str,
    repo_scope: str,
    session_id: str,
    repo_head: str,
    worktree_digest: str,
    state_epoch: int,
    now: str,
) -> dict[str, object]:
    """Fail closed unless both output and current builder authority are still valid."""
    required = {
        "schema_version",
        "session_binding_digest",
        "state_epoch",
        "output_id",
        "kind",
        "revision",
        "content_digest",
        "output_binding_digest",
    }
    if not isinstance(output, Mapping) or set(output) != required:
        raise ValueError("invalid builder output schema")
    if output.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported builder output schema")

    kind = output.get("kind")
    if kind not in _ALLOWED_KINDS:
        raise ValueError("invalid output kind")
    capability = _KIND_CAPABILITY[kind]

    # This revalidates exact chat/project/repo/session/worktree/epoch/TTL authority.
    authorized_session = authorize_builder_action(
        session,
        chat_id=chat_id,
        project_id=project_id,
        repo_scope=repo_scope,
        session_id=session_id,
        repo_head=repo_head,
        worktree_digest=worktree_digest,
        state_epoch=state_epoch,
        capability=capability,
        now=now,
    )

    session_binding = output.get("session_binding_digest")
    if session_binding != authorized_session.get("binding_digest"):
        raise PermissionError("builder output session binding mismatch")
    if output.get("state_epoch") != state_epoch:
        raise PermissionError("builder output state epoch changed")

    output_id = output.get("output_id")
    revision = output.get("revision")
    content_digest = output.get("content_digest")
    binding_digest = output.get("output_binding_digest")
    if not isinstance(output_id, str) or not _OUTPUT_ID_RE.fullmatch(output_id):
        raise ValueError("invalid output_id")
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1 or revision > MAX_REVISION:
        raise ValueError("invalid output revision")
    if not isinstance(content_digest, str) or not _DIGEST_RE.fullmatch(content_digest):
        raise ValueError("invalid content_digest")
    if not isinstance(binding_digest, str) or not _DIGEST_RE.fullmatch(binding_digest):
        raise ValueError("invalid output binding")

    payload = {
        "schema_version": SCHEMA_VERSION,
        "session_binding_digest": session_binding,
        "state_epoch": output.get("state_epoch"),
        "output_id": output_id,
        "kind": kind,
        "revision": revision,
        "content_digest": content_digest,
    }
    if binding_digest != _digest(payload):
        raise ValueError("builder output was modified")
    return dict(output)
