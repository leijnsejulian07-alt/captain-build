"""Bind OpenBuilder lifecycle creation to Captain's canonical context gateway.

Adapters call this bridge instead of opening builder sessions directly. Captain
assembles memory/context first, verifies the active Project State epoch, then
opens the lifecycle under the exact same authority. Downstream builder outputs
must carry the exact session token issued by this bridge.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Mapping, Tuple

from .builder_action_receipts import BuilderActionReceipt
from .builder_lifecycle import BuilderLifecycleCoordinator
from .builder_resource_store import BuilderResource
from .builder_update_stream import BuilderUpdate
from .project_authority import AuthorityError, ProjectAuthority, require_current_epoch
from .request_context_gateway import BuilderContextEnvelope, RequestContextGateway


@dataclass(frozen=True)
class BuilderSessionStart:
    """Opaque Captain-issued context/session binding for downstream builder work."""

    context: BuilderContextEnvelope
    session: BuilderResource


BuilderSessionKey = Tuple[str, str, str, int, str]


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
        self._starts: Dict[BuilderSessionKey, BuilderSessionStart] = {}

    @staticmethod
    def _key(authority: ProjectAuthority, session_id: str) -> BuilderSessionKey:
        if authority.is_normal_chat:
            raise AuthorityError("builder session key requires project authority")
        assert authority.chat_id is not None
        assert authority.project_id is not None
        assert authority.repo_scope is not None
        assert authority.state_epoch is not None
        return (
            authority.chat_id,
            authority.project_id,
            authority.repo_scope,
            authority.state_epoch,
            session_id,
        )

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
        start = BuilderSessionStart(context=context, session=session)
        self._starts[self._key(context.authority, session_id)] = start
        return start

    def _adopt_rehydrated_session(
        self,
        *,
        context: BuilderContextEnvelope,
        session: BuilderResource,
        current_epoch: int,
    ) -> BuilderSessionStart:
        """Register a fully staged restart session after re-proving Captain context.

        This is intentionally package-private. Restart code must first build an
        isolated lifecycle and validate all persisted phase/job state. This method
        only issues the normal opaque session token after the canonical gateway
        independently recreates the exact same context and the staged lifecycle
        proves that the session and phase checkpoint are live.
        """
        if type(context) is not BuilderContextEnvelope or type(session) is not BuilderResource:
            raise AuthorityError("rehydration requires canonical Captain session state")
        authority = context.authority
        authority.require_same_owner(session.authority)
        require_current_epoch(authority, current_epoch=current_epoch)
        if context.current_epoch != current_epoch:
            raise AuthorityError("rehydrated builder context epoch is stale")
        if session.resource_type != "session":
            raise AuthorityError("rehydration requires a builder session resource")

        fresh = self._gateway.for_builder(
            request=authority,
            current_epoch=current_epoch,
            capabilities=context.capabilities,
        )
        if fresh != context:
            raise AuthorityError("rehydrated builder context no longer matches Captain state")

        stored = self._lifecycle.resources.get(
            session.resource_id,
            request=authority,
            current_epoch=current_epoch,
            resource_type="session",
        )
        if stored is None or stored != session:
            raise AuthorityError("rehydrated builder session is not live in the staged lifecycle")
        self._lifecycle.phases.export_state(
            authority=authority,
            session_id=session.resource_id,
            current_epoch=current_epoch,
        )

        key = self._key(authority, session.resource_id)
        if key in self._starts:
            raise AuthorityError("rehydrated builder session token is already registered")
        start = BuilderSessionStart(context=context, session=session)
        self._starts[key] = start
        return start

    def _require_start(
        self,
        start: BuilderSessionStart,
        *,
        current_epoch: int,
    ) -> BuilderSessionStart:
        if type(start) is not BuilderSessionStart:
            raise AuthorityError("builder work requires a canonical session token")
        authority = start.context.authority
        authority.require_same_owner(start.session.authority)
        require_current_epoch(authority, current_epoch=current_epoch)
        if start.context.current_epoch != current_epoch:
            raise AuthorityError("builder context epoch is stale")
        key = self._key(authority, start.session.resource_id)
        if self._starts.get(key) is not start:
            raise AuthorityError("unknown or forged builder session token")
        stored = self._lifecycle.resources.get(
            start.session.resource_id,
            request=authority,
            current_epoch=current_epoch,
            resource_type="session",
        )
        if stored is None or stored != start.session:
            raise AuthorityError("builder session is no longer live")
        return start

    def record_action(
        self,
        start: BuilderSessionStart,
        receipt: BuilderActionReceipt,
        *,
        current_epoch: int,
    ) -> None:
        bound = self._require_start(start, current_epoch=current_epoch)
        if receipt.session_id != bound.session.resource_id:
            raise AuthorityError("builder action belongs to a different session")
        bound.context.authority.require_same_owner(receipt.authority)
        self._lifecycle.record_action(
            receipt,
            actor=bound.context.authority,
            current_epoch=current_epoch,
        )

    def publish_update(
        self,
        start: BuilderSessionStart,
        update: BuilderUpdate,
        *,
        current_epoch: int,
    ) -> bool:
        bound = self._require_start(start, current_epoch=current_epoch)
        if update.session_id != bound.session.resource_id:
            raise AuthorityError("builder update belongs to a different session")
        bound.context.authority.require_same_owner(update.authority)
        return self._lifecycle.publish_update(
            update,
            actor=bound.context.authority,
            current_epoch=current_epoch,
        )

    def put_resource(
        self,
        start: BuilderSessionStart,
        resource: BuilderResource,
        *,
        current_epoch: int,
    ) -> None:
        bound = self._require_start(start, current_epoch=current_epoch)
        bound.context.authority.require_same_owner(resource.authority)
        self._lifecycle.put_resource(
            resource,
            session_id=bound.session.resource_id,
            actor=bound.context.authority,
            current_epoch=current_epoch,
        )
