"""Acceptance contract: durable Project Memory vs transient chat-context isolation.

Design invariant:
- Project Memory is persistent project knowledge. It may be reused by another chat only
  inside the exact same complete (project_id, repo_scope, state_epoch) wall.
- Transient chat context/session state is additionally owned by chat_id and must never
  cross to another chat, even inside the same project.
- Normal chats remain isolated by chat_id.
- Partial/invalid project scopes and invalid chat ids fail closed.
"""

from dataclasses import dataclass

from project_scope_contract import Scope


def _valid_chat_id(chat_id):
    return isinstance(chat_id, str) and bool(chat_id.strip())


@dataclass(frozen=True)
class RequestContext:
    chat_id: str
    scope: Scope

    def validate(self):
        if not _valid_chat_id(self.chat_id):
            raise ValueError("invalid chat_id must fail closed")
        self.scope.validate()


@dataclass(frozen=True)
class MemoryRecord:
    record_id: str
    scope: Scope


@dataclass(frozen=True)
class ChatContextRecord:
    record_id: str
    chat_id: str
    scope: Scope


def project_memory_readable(record, request):
    request.validate()
    record.scope.validate()

    if request.scope.is_normal:
        return record.scope.is_normal

    # Durable project memory intentionally survives chat changes, but never project,
    # repository, or Project State epoch changes.
    return record.scope == request.scope


def chat_context_readable(record, request):
    request.validate()
    record.scope.validate()
    if not _valid_chat_id(record.chat_id):
        raise ValueError("invalid stored chat_id must fail closed")

    # Transient context is stricter than project memory: chat_id must also match.
    return record.chat_id == request.chat_id and record.scope == request.scope


def test_project_memory_can_cross_chat_inside_same_epoch_wall():
    scope = Scope("project-a", "repo/main", 8)
    memory = MemoryRecord("m1", scope)
    assert project_memory_readable(memory, RequestContext("chat-a", scope))
    assert project_memory_readable(memory, RequestContext("chat-b", scope))


def test_project_memory_cannot_cross_project_repo_or_epoch():
    scope = Scope("project-a", "repo/main", 8)
    memory = MemoryRecord("m1", scope)
    assert not project_memory_readable(
        memory, RequestContext("chat-b", Scope("project-b", "repo/main", 8))
    )
    assert not project_memory_readable(
        memory, RequestContext("chat-b", Scope("project-a", "repo/other", 8))
    )
    assert not project_memory_readable(
        memory, RequestContext("chat-b", Scope("project-a", "repo/main", 9))
    )


def test_transient_context_cannot_cross_chat():
    scope = Scope("project-a", "repo/main", 8)
    context = ChatContextRecord("c1", "chat-a", scope)
    assert chat_context_readable(context, RequestContext("chat-a", scope))
    assert not chat_context_readable(context, RequestContext("chat-b", scope))


def test_normal_chats_are_also_chat_isolated():
    context = ChatContextRecord("c1", "normal-a", Scope())
    assert chat_context_readable(context, RequestContext("normal-a", Scope()))
    assert not chat_context_readable(context, RequestContext("normal-b", Scope()))


def test_invalid_chat_ids_fail_closed():
    scope = Scope("project-a", "repo/main", 8)
    memory = MemoryRecord("m1", scope)
    for chat_id in (None, "", " ", 7, True):
        try:
            project_memory_readable(memory, RequestContext(chat_id, scope))
        except ValueError:
            continue
        raise AssertionError(f"invalid chat_id accepted: {chat_id!r}")


if __name__ == "__main__":
    test_project_memory_can_cross_chat_inside_same_epoch_wall()
    test_project_memory_cannot_cross_project_repo_or_epoch()
    test_transient_context_cannot_cross_chat()
    test_normal_chats_are_also_chat_isolated()
    test_invalid_chat_ids_fail_closed()
    print("MEMORY_CHAT_CONTEXT_WALL_PASS")
