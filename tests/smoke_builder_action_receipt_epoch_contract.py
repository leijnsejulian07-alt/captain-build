"""Fail-closed builder action receipt epoch contract.

Fallback acceptance contract only; live Captain integration still requires local
reconciliation and regressions against the real OpenBuilder implementation.
"""

from dataclasses import dataclass

from project_scope_contract import Scope


@dataclass(frozen=True)
class BuilderActionReceipt:
    action_id: str
    session_id: str
    chat_id: str
    project_id: str
    repo_scope: str
    state_epoch: int

    def validate(self) -> None:
        if not self.action_id.strip() or not self.session_id.strip() or not self.chat_id.strip():
            raise ValueError("receipt identifiers must be non-empty")
        Scope(self.project_id, self.repo_scope, self.state_epoch).validate()


def accepts(receipt: BuilderActionReceipt, *, chat_id: str, scope: Scope) -> bool:
    try:
        receipt.validate()
        scope.validate()
    except (ValueError, AttributeError):
        return False
    if scope.is_normal:
        return False
    return (
        receipt.chat_id == chat_id
        and receipt.project_id == scope.project_id
        and receipt.repo_scope == scope.repo_scope
        and receipt.state_epoch == scope.state_epoch
    )


def main() -> None:
    receipt = BuilderActionReceipt("act-1", "session-1", "chat-a", "project-a", "repo-a", 7)
    current = Scope("project-a", "repo-a", 7)
    assert accepts(receipt, chat_id="chat-a", scope=current)

    # Epoch is explicit on the receipt and must match the current Project State.
    assert not accepts(receipt, chat_id="chat-a", scope=Scope("project-a", "repo-a", 6))
    assert not accepts(receipt, chat_id="chat-a", scope=Scope("project-a", "repo-a", 8))

    # Every ownership dimension independently fails closed.
    assert not accepts(receipt, chat_id="chat-b", scope=current)
    assert not accepts(receipt, chat_id="chat-a", scope=Scope("project-b", "repo-a", 7))
    assert not accepts(receipt, chat_id="chat-a", scope=Scope("project-a", "repo-b", 7))

    # Normal/partial/invalid scope cannot consume a project-bound receipt.
    assert not accepts(receipt, chat_id="chat-a", scope=Scope())
    assert not accepts(receipt, chat_id="chat-a", scope=Scope("project-a", None, 7))
    assert not accepts(receipt, chat_id="chat-a", scope=Scope("project-a", "repo-a", -1))

    # Invalid receipt epochs fail closed rather than inheriting session authority.
    bad = BuilderActionReceipt("act-2", "session-1", "chat-a", "project-a", "repo-a", -1)
    assert not accepts(bad, chat_id="chat-a", scope=current)


if __name__ == "__main__":
    main()
