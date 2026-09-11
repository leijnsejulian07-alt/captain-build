"""Bind OpenBuilder lifecycle creation to Captain's canonical context gateway.

Adapters call this bridge instead of opening builder sessions directly. Captain
assembles memory/context first, verifies the active Project State epoch, then
opens the lifecycle under the exact same authority.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Tuple

from .builder_lifecycle import BuilderLifecycleCoordinator
from .builder_resource_store import BuilderResource
from .project_authority import AuthorityError, ProjectAuthority
from .request_context_gateway import BuilderContextEnvelope, RequestContextGateway


@dataclass(frozen=True)
class BuilderSessionStart:
    """Canonical context plus the Captain-owned session it authorized."""

    context: BuilderContextEnvelope
    session: BuilderResource


class ContextBoundBuilder:
    """OpenBuilder entry point that cannot bypass Captain context assembly."""

    def __init__(
        self,
        *,
        gateway: RequestContextGateway,
        lifecycle: BuilderLifecycleCoordinator,
    ) -> None:
        if type(gateway) is not RequestContextGateway:
            raise AuthorityError("builder requires canonical RequestContextGateway")
        if type(lifecycle) is not BuilderLifecycleCoordinator:
            raise AuthorityError("builder requires canonical lifecycle coordinator")
        self._gateway = gateway
        self._lifecycle = lifecycle

    def open_session(
        self,
        session_id: str,
        *,
        request: ProjectAuthority,
        current_epoch: int,
        capabilities: Tuple[str, ...] = (),
        payload: Mapping[str, object],
    ) -> BuilderSessionStart:
        context = self._gateway.for_builder(
            request=request,
            current_epoch=current_epoch,
            capabilities=capabilities,
        )
        session = self._lifecycle.open_session(
            session_id,
            actor=context.authority,
            current_epoch=context.current_epoch,
            payload=payload,
        )
        if session.authority != context.authority:
            raise AuthorityError("builder session authority mismatch")
        return BuilderSessionStart(context=context, session=session)

    @property
    def lifecycle(self) -> BuilderLifecycleCoordinator:
        """Expose the canonical lifecycle for downstream action/update methods."""

        return self._lifecycle
