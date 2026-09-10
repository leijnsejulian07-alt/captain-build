"""Epoch-bound OpenBuilder resource registry for Captain.

Captain remains the authority/control-plane. Builder implementations may produce
sessions, previews, console streams, diffs, rollback points, context and updates,
but every resource is owned by one validated ProjectAuthority and can only be
resolved by that exact current authority epoch.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Mapping, Optional

from .project_authority import AuthorityError, ProjectAuthority, require_current_epoch


ALLOWED_BUILDER_RESOURCE_TYPES = frozenset(
    {
        "session",
        "preview",
        "console",
        "diff",
        "rollback",
        "builder_context",
        "builder_update",
    }
)


@dataclass(frozen=True)
class BuilderResource:
    resource_type: str
    resource_id: str
    authority: ProjectAuthority
    payload: Mapping[str, object]

    def validate(self) -> "BuilderResource":
        if self.resource_type not in ALLOWED_BUILDER_RESOURCE_TYPES:
            raise AuthorityError("unknown builder resource type must fail closed")
        if not isinstance(self.resource_id, str) or not self.resource_id.strip():
            raise AuthorityError("builder resource requires a non-empty resource_id")
        self.authority.validate()
        if self.authority.is_normal_chat:
            raise AuthorityError("builder resources require complete project authority")
        return self


class EpochBoundBuilderResourceStore:
    """Fail-closed registry for Captain-owned OpenBuilder resources.

    This class deliberately does not execute builder code. It is the ownership
    boundary that adapters/subsystems must cross before Captain exposes a
    session, preview, console stream, diff, rollback point, context, or update.
    """

    def __init__(self) -> None:
        self._resources: Dict[str, BuilderResource] = {}

    def put(
        self,
        resource: BuilderResource,
        *,
        actor: ProjectAuthority,
        current_epoch: int,
    ) -> None:
        actor.validate()
        if actor.is_normal_chat:
            raise AuthorityError("normal chat cannot own builder resources")
        require_current_epoch(actor, current_epoch=current_epoch)
        resource.validate()
        actor.require_same_owner(resource.authority)

        existing = self._resources.get(resource.resource_id)
        if existing is not None and not existing.authority.same_owner(actor):
            raise AuthorityError("builder resource_id collision across authority wall")
        self._resources[resource.resource_id] = resource

    def get(
        self,
        resource_id: str,
        *,
        request: ProjectAuthority,
        current_epoch: int,
        resource_type: Optional[str] = None,
    ) -> Optional[BuilderResource]:
        self._validate_request(request, current_epoch=current_epoch)
        if resource_type is not None and resource_type not in ALLOWED_BUILDER_RESOURCE_TYPES:
            raise AuthorityError("unknown builder resource type must fail closed")

        resource = self._resources.get(resource_id)
        if resource is None:
            return None
        resource.validate()
        if resource_type is not None and resource.resource_type != resource_type:
            return None
        if not resource.authority.same_owner(request):
            return None
        return resource

    def list_readable(
        self,
        *,
        request: ProjectAuthority,
        current_epoch: int,
        resource_type: Optional[str] = None,
    ) -> List[BuilderResource]:
        self._validate_request(request, current_epoch=current_epoch)
        if resource_type is not None and resource_type not in ALLOWED_BUILDER_RESOURCE_TYPES:
            raise AuthorityError("unknown builder resource type must fail closed")

        return [
            resource
            for resource in self._resources.values()
            if (resource_type is None or resource.resource_type == resource_type)
            and resource.authority.same_owner(request)
        ]

    def revoke_epoch(
        self,
        *,
        authority: ProjectAuthority,
        current_epoch: int,
    ) -> int:
        """Drop resources for an old epoch after a Project State transition.

        The caller must itself be the currently active epoch. Only resources
        matching the same chat/project/repo but a different epoch are removed.
        This is cleanup, not the security boundary: stale reads are already
        denied by current-epoch validation.
        """
        authority.validate()
        if authority.is_normal_chat:
            raise AuthorityError("normal chat cannot revoke builder epochs")
        require_current_epoch(authority, current_epoch=current_epoch)

        doomed = [
            resource_id
            for resource_id, resource in self._resources.items()
            if (
                resource.authority.chat_id == authority.chat_id
                and resource.authority.project_id == authority.project_id
                and resource.authority.repo_scope == authority.repo_scope
                and resource.authority.state_epoch != authority.state_epoch
            )
        ]
        for resource_id in doomed:
            del self._resources[resource_id]
        return len(doomed)

    @staticmethod
    def _validate_request(request: ProjectAuthority, *, current_epoch: int) -> None:
        request.validate()
        if request.is_normal_chat:
            raise AuthorityError("normal chat cannot access builder resources")
        require_current_epoch(request, current_epoch=current_epoch)
