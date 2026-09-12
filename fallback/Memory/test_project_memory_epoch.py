import pytest

from project_memory_epoch import (
    MemoryEnvelope,
    assert_memory_access,
    build_memory,
    distill_shared,
)


def project_memory(**overrides):
    args = {
        "memory_id": "m-1",
        "kind": "project_context",
        "payload": {"summary": "safe project context"},
        "chat_id": "chat-a",
        "project_id": "project-a",
        "repo_scope": "owner/repo@main",
        "state_epoch": 7,
    }
    args.update(overrides)
    return build_memory(**args)


def authority(**overrides):
    args = {
        "chat_id": "chat-a",
        "project_id": "project-a",
        "repo_scope": "owner/repo@main",
        "state_epoch": 7,
    }
    args.update(overrides)
    return args


def test_current_project_epoch_can_read_memory():
    memory = project_memory()
    assert_memory_access(memory, **authority())
    assert memory.scope == "project"
    assert memory.public_metadata() == {
        "memory_id": "m-1",
        "kind": "project_context",
        "scope": "project",
        "authority_bound": True,
    }


def test_epoch_change_makes_old_memory_inaccessible():
    memory = project_memory(state_epoch=7)
    with pytest.raises(PermissionError):
        assert_memory_access(memory, **authority(state_epoch=8))


@pytest.mark.parametrize(
    "foreign",
    [
        {"chat_id": "chat-b"},
        {"project_id": "project-b"},
        {"repo_scope": "owner/other@main"},
    ],
)
def test_cross_chat_project_or_repo_memory_is_denied(foreign):
    memory = project_memory()
    with pytest.raises(PermissionError):
        assert_memory_access(memory, **authority(**foreign))


def test_missing_project_authority_fails_closed():
    memory = project_memory()
    with pytest.raises(PermissionError):
        assert_memory_access(memory, chat_id="chat-a")


def test_normal_non_project_chat_still_works_without_project_state():
    memory = build_memory(
        memory_id="chat-context-1",
        kind="chat_context",
        payload={"topic": "ordinary question"},
        chat_id="normal-chat",
    )
    assert_memory_access(memory, chat_id="normal-chat")
    with pytest.raises(PermissionError):
        assert_memory_access(memory, chat_id="other-chat")
    with pytest.raises(PermissionError):
        assert_memory_access(
            memory,
            chat_id="normal-chat",
            project_id="p",
            repo_scope="r",
            state_epoch=1,
        )


def test_chat_context_cannot_accidentally_gain_project_authority():
    with pytest.raises(ValueError):
        build_memory(
            memory_id="chat-context-2",
            kind="chat_context",
            payload={"topic": "ordinary"},
            chat_id="chat-a",
            project_id="project-a",
            repo_scope="owner/repo",
            state_epoch=1,
        )


def test_project_memory_requires_complete_epoch_authority():
    with pytest.raises(ValueError):
        project_memory(state_epoch=None)
    with pytest.raises(ValueError):
        project_memory(state_epoch=0)
    with pytest.raises(ValueError):
        project_memory(state_epoch=True)


def test_scope_and_secret_fields_cannot_be_smuggled_in_payload():
    for key in ("chat_id", "project_id", "repo_scope", "state_epoch", "token", "api_key", "password"):
        with pytest.raises(ValueError):
            project_memory(payload={key: "should-not-live-in-payload"})


def test_shared_learning_is_explicitly_unscoped_and_project_neutral():
    project = project_memory()
    shared = distill_shared(project, distilled_payload={"lesson": "generic retry strategy"})
    assert shared.scope == "global"
    assert shared.authority_digest is None
    assert_memory_access(shared)
    with pytest.raises(ValueError):
        build_memory(
            memory_id="bad-global",
            kind="shared_learning",
            payload={"lesson": "x"},
            chat_id="chat-a",
        )


def test_tampered_or_invalid_envelope_fails_closed():
    forged = MemoryEnvelope(
        memory_id="m-forged",
        kind="project_context",
        scope="project",
        authority_digest="0" * 64,
        payload={"summary": "x"},
    )
    with pytest.raises(PermissionError):
        assert_memory_access(forged, **authority())

    invalid_global = MemoryEnvelope(
        memory_id="m-global",
        kind="project_fact",
        scope="global",
        authority_digest=None,
        payload={"summary": "x"},
    )
    with pytest.raises(PermissionError):
        assert_memory_access(invalid_global)
