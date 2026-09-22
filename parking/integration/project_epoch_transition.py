from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Mapping, Protocol

from parking.integration.scope_contract import parse_scope


class EpochTransitionError(ValueError):
    pass


_CLEANUP_NAME_RE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_RESERVED_CLEANUP = "builder_outputs"


@dataclass(frozen=True)
class EpochTransitionResult:
    previous_epoch: int
    current_epoch: int
    revoked_builder_handles: int
    cleanup_counts: tuple[tuple[str, int], ...] = ()


class SupportsEpochCleanup(Protocol):
    def revoke_stale_epochs(self, *, chat_id: str, project_id: str, repo_scope: str, current_epoch: int) -> int: ...


def _validate_cleanup(name: str, cleanup: object) -> SupportsEpochCleanup:
    if not isinstance(name, str) or not _CLEANUP_NAME_RE.fullmatch(name):
        raise EpochTransitionError("invalid epoch cleanup name")
    if cleanup is None or not callable(getattr(cleanup, "revoke_stale_epochs", None)):
        raise EpochTransitionError(f"invalid epoch cleanup dependency: {name}")
    return cleanup  # type: ignore[return-value]


def apply_project_epoch_transition(
    *,
    chat_id: str,
    project_id: str,
    repo_scope: str,
    previous_epoch: int,
    current_epoch: int,
    builder_outputs: SupportsEpochCleanup,
    additional_cleanups: Mapping[str, SupportsEpochCleanup] | None = None,
) -> EpochTransitionResult:
    """Apply bounded security cleanup for one verified Captain Project State transition.

    Captain remains the sole Project State authority. This hook never advances state; it
    revokes stale resources only after the caller supplies one exact monotonic transition.
    All cleanup dependencies are validated before the first side effect. Additional cleanup
    adapters let sessions/context/memory share this single transition boundary instead of
    growing independent epoch hooks. A cleanup failure is surfaced fail-closed; already
    completed revocations are intentionally not rolled back because restoring stale
    capability would be less safe than leaving it revoked.
    """
    parse_scope({"chat_id": chat_id, "project_id": project_id, "repo_scope": repo_scope})
    for name, value in (("previous_epoch", previous_epoch), ("current_epoch", current_epoch)):
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise EpochTransitionError(f"invalid {name}")
    if current_epoch <= previous_epoch:
        raise EpochTransitionError("Project State epoch must advance monotonically")

    primary = _validate_cleanup(_RESERVED_CLEANUP, builder_outputs)
    cleanups: list[tuple[str, SupportsEpochCleanup]] = [(_RESERVED_CLEANUP, primary)]
    if additional_cleanups is not None:
        if not isinstance(additional_cleanups, Mapping):
            raise EpochTransitionError("additional_cleanups must be a mapping")
        seen_ids = {id(primary)}
        for name in sorted(additional_cleanups):
            if name == _RESERVED_CLEANUP:
                raise EpochTransitionError("reserved epoch cleanup name")
            cleanup = _validate_cleanup(name, additional_cleanups[name])
            if id(cleanup) in seen_ids:
                raise EpochTransitionError("duplicate epoch cleanup dependency")
            seen_ids.add(id(cleanup))
            cleanups.append((name, cleanup))

    counts: list[tuple[str, int]] = []
    for name, cleanup in cleanups:
        try:
            revoked = cleanup.revoke_stale_epochs(
                chat_id=chat_id,
                project_id=project_id,
                repo_scope=repo_scope,
                current_epoch=current_epoch,
            )
        except Exception as exc:
            raise EpochTransitionError(f"epoch cleanup failed: {name}") from exc
        if isinstance(revoked, bool) or not isinstance(revoked, int) or revoked < 0:
            raise EpochTransitionError(f"invalid epoch cleanup result: {name}")
        counts.append((name, revoked))

    return EpochTransitionResult(
        previous_epoch=previous_epoch,
        current_epoch=current_epoch,
        revoked_builder_handles=counts[0][1],
        cleanup_counts=tuple(counts),
    )
