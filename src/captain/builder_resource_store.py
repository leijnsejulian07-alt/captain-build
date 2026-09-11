"""Epoch-bound OpenBuilder resource registry for Captain.

Captain remains the authority/control-plane. Builder implementations may produce
sessions, previews, console streams, diffs, rollback points, context and updates,
but every resource is owned by one validated ProjectAuthority and can only be
resolved by that exact current authority epoch.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from types import MappingProxyType
from typing import Dict, List, Mapping, Optional, Tuple

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

BuilderResourceKey = Tuple[str, str, str, int, str, str]


def _freeze_payload_value(value: object, *, path: str = "$") -> object:
    """Snapshot a builder payload into immutable JSON-like builtin values.

    The resource store is an authority boundary. Retaining caller-owned nested
    dict/list objects after authorization would allow a builder adapter to mutate
    a preview/session/diff after the check. Custom objects are rejected rather
    than copied so provider/plugin hooks cannot execute inside this boundary.
    """

    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise AuthorityError(f"builder payload contains non-finite float at {path}")
        return value
    if type(value) is dict:
        frozen: Dict[str, object] = {}
        for key, nested in value.items():
            if not isinstance(key, str) or not key:
                raise AuthorityError(
                    f"builder payload keys must be non-empty strings at {path}"
                )
            frozen[key] = _freeze_payload_value(nested, path=f"{path}.{key}")
        return MappingProxyType(frozen)
    if type(value) in {list, tuple}:
        return tuple(
            _freeze_payload_value(nested, path=f"{path}[{index}]")
            for index, nested in enumerate(value)
        )
    raise AuthorityError(
        "builder payload contains unsupported mutable/custom value "
        f"at {path}: {type(value).__name__}"
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
        if type(self.payload) is not dict and not isinstance(self.payload, MappingProxyType):
            raise AuthorityError("builder resource payload must be a canonical mapping")
        return self


def _snapshot_resource(resource: BuilderResource) -> BuilderResource:
    resource.validate()
    payload = _freeze_payload_value(dict(resource.payload))
    assert isinstance(payload, Mapping)
    return BuilderResource(
        resource_type=resource.resource_type,
        resource_id=resource.resource_id,
        authority=resource.authority,
        payload=payload,
    )


class EpochBoundBuilderResourceStore:
    """Fail-closed registry for Captain-owned OpenBuilder resources.

    This class deliberately does not execute builder code. It is the ownership
    boundary that adapters/subsystems must cross before Captain exposes a
    session, preview, console stream, diff, rollback point, context, or update.

    Resource identity is authority- and type-scoped. Different projects, Project
    State epochs, and resource kinds may legitimately reuse provider-local IDs
    such as ``1`` or ``current`` without blocking or overwriting one another.
    """

    def __init__(self) -> None:
        self._resources: Dict[BuilderResourceKey, BuilderResource] = {}

    @staticmethod
    def _storage_key(
        authority: ProjectAuthority,
        resource_type: str,
        resource_id: str,
    ) -> BuilderResourceKey:
        authority.validate()
        if authority.is_normal_chat:
            raise AuthorityError("normal chat cannot own builder resources")
        if resource_type not in ALLOWED_BUILDER_RESOURCE_TYPES:
            raise AuthorityError("unknown builder resource type must fail closed")
        if not isinstance(resource_id, str) or not resource_id.strip():
            raise AuthorityError("builder resource requires a non-empty resource_id")
        assert authority.chat_id is not None
        assert authority.project_id is not None
        assert authority.repo_scope is not None
        assert authority.state_epoch is not None
        return (
            authority.chat_id,
            authority.project_id,
            authority.repo_scope,
            authority.state_epoch,
            resource_type,
            resource_id,
        )

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

        snapshot = _snapshot_resource(resource)
        key = self._storage_key(actor, resource.resource_type, resource.resource_id)
        self._resources[key] = snapshot

    def get(
        self,
        resource_id: str,
        *,
        request: ProjectAuthority,
        current_epoch: int,
        resource_type: Optional[str] = None,
    ) -> Optional[BuilderResource]:
        self._validate_request(request, current_epoch=current_epoch)
        if not isinstance(resource_id, str) or not resource_id.strip():
            raise AuthorityError("builder resource requires a non-empty resource_id")
        if resource_type is not None and resource_type not in ALLOWED_BUILDER_RESOURCE_TYPES:
            raise AuthorityError("unknown builder resource type must fail closed")

        if resource_type is not None:
            resource = self._resources.get(
                self._storage_key(request, resource_type, resource_id)
            )
            if resource is None:
                return None
            resource.validate()
            if not resource.authority.same_owner(request):
                raise AuthorityError("builder resource storage key/authority mismatch")
            return resource

        matches = [
            resource
            for resource in self._resources.values()
            if resource.resource_id == resource_id
            and resource.authority.same_owner(request)
        ]
        if not matches:
            return None
        if len(matches) > 1:
            raise AuthorityError(
                "ambiguous builder resource_id requires explicit resource_type"
            )
        matches[0].validate()
        return matches[0]

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
        """Drop resources for old epochs after a Project State transition.

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
            key
            for key, resource in self._resources.items()
            if (
                resource.authority.chat_id == authority.chat_id
                and resource.authority.project_id == authority.project_id
                and resource.authority.repo_scope == authority.repo_scope
                and resource.authority.state_epoch != authority.state_epoch
            )
        ]
        for key in doomed:
            del self._resources[key]
        return len(doomed)

    @staticmethod
    def _validate_request(request: ProjectAuthority, *, current_epoch: int) -> None:
        request.validate()
        if request.is_normal_chat:
            raise AuthorityError("normal chat cannot access builder resources")
        require_current_epoch(request, current_epoch=current_epoch)
