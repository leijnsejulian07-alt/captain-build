"""Parking reference for Captain builder publication authority.

No repo/network writes. Captain remains the sole authority source.
"""
from dataclasses import dataclass
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


def authorize_publication(*, session: PublicationAuthority,
                          current: PublicationAuthority,
                          diff: Mapping[str, str], reviewed: bool) -> tuple[str, ...]:
    """Return paths eligible for publish, or fail closed.

    Native worker/session IDs never grant authority. The entire Captain tuple,
    epoch and checkpoint must still match at publication time.
    """
    session.validate(); current.validate()
    if session != current:
        raise PublicationDenied("publication authority is stale or mismatched")
    if reviewed is not True:
        raise PublicationDenied("reviewable diff approval required")
    if not isinstance(diff, Mapping) or not diff:
        raise PublicationDenied("non-empty reviewable diff required")
    paths = []
    for path, content in diff.items():
        if not isinstance(path, str) or not path or path.startswith("/") or "\\" in path:
            raise PublicationDenied("invalid diff path")
        parts = path.split("/")
        if any(p in ("", ".", "..") for p in parts) or ":" in parts[0]:
            raise PublicationDenied("invalid diff path")
        if not isinstance(content, str):
            raise PublicationDenied("invalid diff content")
        paths.append(path)
    return tuple(sorted(paths))
