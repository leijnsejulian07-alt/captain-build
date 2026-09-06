"""
Captain chat isolation acceptance contract.

Fallback-only, provider-free regression specification.
This intentionally does NOT patch production code. It gives the next local
integration run an executable contract for the required Project State walls.

Expected production semantics:
- Normal chat remains usable without project scope.
- Project chat requires complete (project_id, repo_scope, state_epoch) scope.
- Cross-project list/read/delete fail closed.
- Chats from a stale Project State epoch are inaccessible after epoch advance.
- Malformed/ambiguous scopes fail closed.
"""

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Scope:
    project_id: Optional[str] = None
    repo_scope: Optional[str] = None
    state_epoch: Optional[int] = None

    @property
    def is_normal_chat(self) -> bool:
        return self.project_id is None and self.repo_scope is None and self.state_epoch is None

    @property
    def is_complete_project_scope(self) -> bool:
        valid_project_id = isinstance(self.project_id, str) and bool(self.project_id.strip())
        valid_repo_scope = isinstance(self.repo_scope, str) and bool(self.repo_scope.strip())
        valid_epoch = type(self.state_epoch) is int and self.state_epoch >= 0
        return valid_project_id and valid_repo_scope and valid_epoch

    def validate(self) -> None:
        if self.is_normal_chat:
            return
        if not self.is_complete_project_scope:
            raise ValueError("partial or invalid project scope must fail closed")


@dataclass
class Chat:
    chat_id: str
    scope: Scope


def visible(chat: Chat, request_scope: Scope) -> bool:
    request_scope.validate()
    chat.scope.validate()

    if request_scope.is_normal_chat:
        return chat.scope.is_normal_chat

    return chat.scope == request_scope


def deletable(chat: Chat, request_scope: Scope) -> bool:
    return visible(chat, request_scope)


def test_normal_chat_works_without_project_scope() -> None:
    normal = Chat("normal-1", Scope())
    assert visible(normal, Scope())


def test_partial_and_malformed_scope_fails_closed() -> None:
    bad_scopes = [
        Scope(project_id="p1"),
        Scope(repo_scope="repo"),
        Scope(state_epoch=1),
        Scope(project_id="p1", repo_scope="repo"),
        Scope(project_id="p1", state_epoch=1),
        Scope(repo_scope="repo", state_epoch=1),
        Scope(" ", "repo", 1),
        Scope("p1", " ", 1),
        Scope("p1", "repo", True),
        Scope("p1", "repo", False),
        Scope("p1", "repo", -1),
    ]
    for scope in bad_scopes:
        try:
            scope.validate()
        except ValueError:
            pass
        else:
            raise AssertionError(f"invalid scope unexpectedly accepted: {scope!r}")


def test_cross_project_visibility_and_delete_are_denied() -> None:
    a = Scope("project-a", "repo/main", 7)
    b = Scope("project-b", "repo/main", 7)
    chat_a = Chat("a-1", a)

    assert visible(chat_a, a)
    assert not visible(chat_a, b)
    assert not deletable(chat_a, b)


def test_cross_repo_visibility_is_denied() -> None:
    a = Scope("project-a", "repo/one", 7)
    other_repo = Scope("project-a", "repo/two", 7)
    chat_a = Chat("a-1", a)

    assert visible(chat_a, a)
    assert not visible(chat_a, other_repo)


def test_stale_epoch_is_revoked() -> None:
    epoch_3 = Scope("project-a", "repo/main", 3)
    epoch_4 = Scope("project-a", "repo/main", 4)
    old_chat = Chat("old", epoch_3)

    assert visible(old_chat, epoch_3)
    assert not visible(old_chat, epoch_4)
    assert not deletable(old_chat, epoch_4)


def test_project_chat_not_visible_in_normal_chat() -> None:
    project = Scope("project-a", "repo/main", 1)
    chat = Chat("project-chat", project)

    assert not visible(chat, Scope())


if __name__ == "__main__":
    tests = [
        test_normal_chat_works_without_project_scope,
        test_partial_and_malformed_scope_fails_closed,
        test_cross_project_visibility_and_delete_are_denied,
        test_cross_repo_visibility_is_denied,
        test_stale_epoch_is_revoked,
        test_project_chat_not_visible_in_normal_chat,
    ]
    for test in tests:
        test()
    print("CHAT_EPOCH_SCOPE_HARDENED_PASS")
