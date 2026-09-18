from __future__ import annotations

from typing import Any, Mapping

from parking.integration.builder_output_handles import BuilderOutputHandleStore
from parking.integration.builder_pane_state import BuilderPaneStateContract, PANE_KINDS, PaneAccessDenied


class BuilderPaneAccessGate:
    """Resolve one builder-pane output only after exact pane authority validation.

    The pane snapshot and the underlying output handle must agree on scope, epoch,
    builder session, kind and *exact* revision.  This prevents a UI from rendering a
    newer (or otherwise substituted) artifact merely because a handle still satisfies
    a looser minimum-revision check.
    """

    def __init__(self, pane_contract: BuilderPaneStateContract, handle_store: BuilderOutputHandleStore):
        self._pane_contract = pane_contract
        self._handle_store = handle_store

    def resolve(
        self,
        pane_state: Mapping[str, Any],
        *,
        kind: str,
        chat_id: str,
        project_id: str,
        repo_scope: str,
        current_epoch: int,
        builder_session_id: str,
        current_revision: int,
        handles: Mapping[str, str | None],
        now: int | None = None,
    ) -> dict[str, Any]:
        if kind not in PANE_KINDS:
            raise PaneAccessDenied("unsupported pane kind")

        self._pane_contract.validate(
            pane_state,
            chat_id=chat_id,
            project_id=project_id,
            repo_scope=repo_scope,
            current_epoch=current_epoch,
            builder_session_id=builder_session_id,
            current_revision=current_revision,
            handles=handles,
        )

        handle_id = handles.get(kind)
        if handle_id is None:
            raise PaneAccessDenied("pane output unavailable")

        try:
            record = self._handle_store.resolve(
                handle_id,
                expected_kind=kind,
                chat_id=chat_id,
                project_id=project_id,
                repo_scope=repo_scope,
                current_epoch=current_epoch,
                builder_session_id=builder_session_id,
                min_revision=current_revision,
                now=now,
            )
        except Exception as exc:
            raise PaneAccessDenied("pane output handle rejected") from exc

        # BuilderOutputHandleStore.resolve intentionally supports minimum revisions for
        # other callers. Interactive pane rendering is stricter: the pane snapshot and
        # artifact must represent exactly the same revision.
        if record.get("revision") != current_revision:
            raise PaneAccessDenied("pane output revision mismatch")
        if record.get("kind") != kind:
            raise PaneAccessDenied("pane output kind mismatch")
        if record.get("handle_id") != handle_id:
            raise PaneAccessDenied("pane output handle mismatch")

        return {
            "handle_id": record["handle_id"],
            "kind": record["kind"],
            "revision": record["revision"],
            "artifact_digest": record["artifact_digest"],
            "expires_at": record["expires_at"],
        }
