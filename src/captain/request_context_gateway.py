"""Canonical Captain gateway for model and OpenBuilder context preparation.

The gateway is intentionally small: it does not route models or run builders.
Its job is to make it difficult for any caller to bypass ProjectAuthority and
ContextAssembler by supplying hand-built memory/context bundles.

Captain remains the only user-facing control-plane. Model adapters and builder
subsystems receive an immutable context envelope produced here from the same
source of truth.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

from .context_assembly import ContextAssembler, PromptContextBundle
from .project_authority import AuthorityError, ProjectAuthority, require_current_epoch


@dataclass(frozen=True)
class ModelContextEnvelope:
    """Immutable context handed to a model/provider adapter."""

    authority: ProjectAuthority
    current_epoch: Optional[int]
    prompt_context: PromptContextBundle


@dataclass(frozen=True)
class BuilderContextEnvelope:
    """Immutable Captain-owned context handed to OpenBuilder/subsystem adapters."""

    authority: ProjectAuthority
    current_epoch: int
    repo_scope: str
    prompt_context: PromptContextBundle
    capabilities: Tuple[str, ...]


class RequestContextGateway:
    """Single preparation path for Captain model and builder context.

    Callers provide only authority and the active Project State epoch. They may
    not inject a preassembled PromptContextBundle. This keeps memory retrieval,
    generic-learning fallback and epoch checks behind one Captain-owned gate.
    """

    def __init__(self, assembler: ContextAssembler) -> None:
        if not isinstance(assembler, ContextAssembler):
            raise AuthorityError("gateway requires Captain ContextAssembler")
        self._assembler = assembler

    def for_model(
        self,
        *,
        request: ProjectAuthority,
        current_epoch: Optional[int] = None,
    ) -> ModelContextEnvelope:
        request.validate()
        if request.is_project_scope:
            if current_epoch is None:
                raise AuthorityError("project model context requires current_epoch")
            require_current_epoch(request, current_epoch=current_epoch)
        elif current_epoch is not None:
            raise AuthorityError("normal chat must not carry a Project State epoch")

        bundle = self._assembler.assemble(
            request=request,
            current_epoch=current_epoch,
        )
        self._require_bundle_matches(
            bundle=bundle,
            request=request,
            current_epoch=current_epoch,
        )
        return ModelContextEnvelope(
            authority=request,
            current_epoch=current_epoch,
            prompt_context=bundle,
        )

    def for_builder(
        self,
        *,
        request: ProjectAuthority,
        current_epoch: int,
        capabilities: Tuple[str, ...] = (),
    ) -> BuilderContextEnvelope:
        request.validate()
        if not request.is_project_scope:
            raise AuthorityError("OpenBuilder requires explicit project authority")
        require_current_epoch(request, current_epoch=current_epoch)
        safe_capabilities = self._validate_capabilities(capabilities)

        bundle = self._assembler.assemble(
            request=request,
            current_epoch=current_epoch,
        )
        self._require_bundle_matches(
            bundle=bundle,
            request=request,
            current_epoch=current_epoch,
        )
        # validate() above guarantees a non-empty repo_scope for project scope.
        assert request.repo_scope is not None
        return BuilderContextEnvelope(
            authority=request,
            current_epoch=current_epoch,
            repo_scope=request.repo_scope,
            prompt_context=bundle,
            capabilities=safe_capabilities,
        )

    @staticmethod
    def _require_bundle_matches(
        *,
        bundle: PromptContextBundle,
        request: ProjectAuthority,
        current_epoch: Optional[int],
    ) -> None:
        """Defend against a compromised/custom assembler returning wrong scope."""
        if type(bundle) is not PromptContextBundle:
            raise AuthorityError("assembler returned invalid prompt context bundle")
        if bundle.authority != request:
            raise AuthorityError("prompt context authority mismatch")
        if bundle.current_epoch != current_epoch:
            raise AuthorityError("prompt context epoch mismatch")

    @staticmethod
    def _validate_capabilities(capabilities: Tuple[str, ...]) -> Tuple[str, ...]:
        if type(capabilities) is not tuple:
            raise AuthorityError("builder capabilities must be an immutable tuple")
        seen = set()
        safe = []
        for capability in capabilities:
            if not isinstance(capability, str):
                raise AuthorityError("builder capability names must be strings")
            value = capability.strip()
            if not value or value != capability:
                raise AuthorityError("invalid builder capability name")
            if len(value) > 128:
                raise AuthorityError("builder capability name is too long")
            if value in seen:
                raise AuthorityError("duplicate builder capability")
            seen.add(value)
            safe.append(value)
        return tuple(safe)
