"""Parking reference for Captain builder publication authority.

No repo/network writes. Captain remains the sole authority source.
"""
from dataclasses import dataclass
from hashlib import sha256
from typing import Mapping


class PublicationDenied(PermissionError):
    pass


@dataclass(frozen=True)
class PublicationAuthority:
    chat_id: str
    project_id: str
    repo_scope: str
    builder_session_id: str
    state_epoch: int
    checkpoint: int

    def validate(self) -> None:
        strings = (self.chat_id, self.project_id, self.repo_scope, self.builder_session_id)
        if any(not isinstance(v, str) or not v.strip() for v in strings):
            raise PublicationDenied("invalid publication authority")
        for value, name in ((self.state_epoch, "epoch"), (self.checkpoint, "checkpoint")):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise PublicationDenied(f"invalid {name}")


def _validated_diff(diff: Mapping[str, str]) -> tuple[tuple[str, str], ...]:
    if not isinstance(diff, Mapping) or not diff:
        raise PublicationDenied("non-empty reviewable diff required")
    items = []
    for path, content in diff.items():
        if not isinstance(path, str) or not path or path.startswith("/") or "\\" in path:
            raise PublicationDenied("invalid diff path")
        parts = path.split("/")
        if any(p in ("", ".", "..") for p in parts) or ":" in parts[0]:
            raise PublicationDenied("invalid diff path")
        if not isinstance(content, str):
            raise PublicationDenied("invalid diff content")
        items.append((path, content))
    return tuple(sorted(items))


def publication_digest(*, authority: PublicationAuthority, diff: Mapping[str, str]) -> str:
    """Bind review to the exact authority and exact bytes proposed for publication."""
    authority.validate()
    h = sha256()
    fields = (authority.chat_id, authority.project_id, authority.repo_scope,
              authority.builder_session_id, str(authority.state_epoch), str(authority.checkpoint))
    for value in fields:
        encoded = value.encode("utf-8")
        h.update(len(encoded).to_bytes(8, "big")); h.update(encoded)
    for path, content in _validated_diff(diff):
        for value in (path, content):
            encoded = value.encode("utf-8")
            h.update(len(encoded).to_bytes(8, "big")); h.update(encoded)
    return h.hexdigest()


def authorize_publication(*, session: PublicationAuthority,
                          current: PublicationAuthority,
                          diff: Mapping[str, str], reviewed_digest: str) -> tuple[str, ...]:
    """Return paths eligible for publish, or fail closed.

    A boolean review flag is intentionally insufficient: approval is bound to
    the exact authority tuple and exact reviewed diff bytes. Any mutation,
    epoch/checkpoint change, or scope change requires a fresh review digest.
    """
    session.validate(); current.validate()
    if session != current:
        raise PublicationDenied("publication authority is stale or mismatched")
    if not isinstance(reviewed_digest, str) or len(reviewed_digest) != 64:
        raise PublicationDenied("review digest required")
    expected = publication_digest(authority=current, diff=diff)
    if reviewed_digest != expected:
        raise PublicationDenied("review is stale or does not match publication")
    return tuple(path for path, _ in _validated_diff(diff))
