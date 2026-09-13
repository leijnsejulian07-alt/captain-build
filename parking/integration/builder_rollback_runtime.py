from __future__ import annotations

import hmac
import threading
from typing import Callable, Mapping, TypeVar

from parking.integration.builder_mutation_receipt import validate_builder_mutation_receipt
from parking.integration.builder_rollback_checkpoint import validate_builder_rollback_checkpoint

T = TypeVar("T")


class BuilderRollbackRuntime:
    """Fail-closed rollback coordinator with single-use checkpoint authority.

    The runtime refuses rollback unless the mutation receipt and rollback
    checkpoint both validate against the same live scope/state and the
    checkpoint target is exactly the mutation receipt's pre-state.
    Authority is burned before the callback executes so a failed rollback
    cannot be replayed without a fresh authorization path.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._consumed: set[str] = set()

    def execute(
        self,
        *,
        mutation_receipt: Mapping[str, object],
        rollback_checkpoint: Mapping[str, object],
        mutation_id: str,
        source_request_id: str,
        chat_id: str,
        project_id: str,
        repo_scope: str,
        state_epoch: int,
        builder_session_id: str,
        revision: int,
        artifact_digest: str,
        review_binding_digest: str,
        handle_scope_digest: str,
        checkpoint_id: str,
        source_action_binding: str,
        session_binding: str,
        context_binding: str,
        current_git_head: str,
        current_worktree_digest: str,
        current_state_digest: str,
        now: str,
        approved: bool,
        apply_rollback: Callable[[Mapping[str, object]], T],
    ) -> T:
        if approved is not True:
            raise PermissionError("rollback requires explicit approval")

        checkpoint_binding = rollback_checkpoint.get("binding_digest")
        if not isinstance(checkpoint_binding, str):
            raise ValueError("rollback checkpoint binding missing")

        receipt = validate_builder_mutation_receipt(
            mutation_receipt,
            mutation_id=mutation_id,
            source_request_id=source_request_id,
            chat_id=chat_id,
            project_id=project_id,
            repo_scope=repo_scope,
            state_epoch=state_epoch,
            builder_session_id=builder_session_id,
            revision=revision,
            artifact_digest=artifact_digest,
            review_binding_digest=review_binding_digest,
            handle_scope_digest=handle_scope_digest,
            current_git_head=current_git_head,
            current_worktree_digest=current_worktree_digest,
            current_state_digest=current_state_digest,
            rollback_checkpoint_binding=checkpoint_binding,
            now=now,
        )
        checkpoint = validate_builder_rollback_checkpoint(
            rollback_checkpoint,
            chat_id=chat_id,
            project_id=project_id,
            repo_scope=repo_scope,
            checkpoint_id=checkpoint_id,
            source_request_id=source_request_id,
            source_action_binding=source_action_binding,
            session_binding=session_binding,
            context_binding=context_binding,
            current_git_head=current_git_head,
            current_worktree_digest=current_worktree_digest,
            current_state_digest=current_state_digest,
            now=now,
        )

        exact_links = (
            ("target_git_head", "pre_git_head"),
            ("target_worktree_digest", "pre_worktree_digest"),
            ("target_state_digest", "pre_state_digest"),
            ("expected_current_git_head", "post_git_head"),
            ("expected_current_worktree_digest", "post_worktree_digest"),
            ("expected_current_state_digest", "post_state_digest"),
        )
        for checkpoint_field, receipt_field in exact_links:
            left = checkpoint.get(checkpoint_field)
            right = receipt.get(receipt_field)
            if not isinstance(left, str) or not isinstance(right, str) or not hmac.compare_digest(left, right):
                raise PermissionError(
                    f"rollback checkpoint {checkpoint_field} does not match mutation receipt {receipt_field}"
                )

        receipt_checkpoint_binding = receipt.get("rollback_checkpoint_binding")
        if (
            not isinstance(receipt_checkpoint_binding, str)
            or not hmac.compare_digest(receipt_checkpoint_binding, checkpoint_binding)
        ):
            raise PermissionError("mutation receipt is not bound to this rollback checkpoint")

        with self._lock:
            if checkpoint_binding in self._consumed:
                raise PermissionError("rollback checkpoint authority already consumed")
            self._consumed.add(checkpoint_binding)

        return apply_rollback(checkpoint)
