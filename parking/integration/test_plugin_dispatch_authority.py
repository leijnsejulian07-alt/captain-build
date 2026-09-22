from __future__ import annotations

from copy import deepcopy

from parking.integration.plugin_dispatch_authority import (
    issue_plugin_dispatch_ticket,
    validate_plugin_dispatch_ticket,
)


def record(**overrides):
    row = {
        "schema_version": 1,
        "plugin_id": "github",
        "installed": True,
        "connected": True,
        "enabled": True,
        "ready": True,
        "auth_method": "oauth",
        "scope": "project",
        "project_id": "project-a",
        "capabilities": ["repo.read", "repo.write"],
        "permissions": ["repo.read", "repo.write"],
        "health": "healthy",
    }
    row.update(overrides)
    return row


def expect(exc_type, fn):
    try:
        fn()
    except exc_type:
        return
    raise AssertionError(f"expected {exc_type.__name__}")


def main():
    records = [record()]
    ticket = issue_plugin_dispatch_ticket(
        records,
        chat_id="chat-a",
        project_id="project-a",
        repo_scope="owner/repo#main",
        state_epoch=7,
        plugin_id="github",
        capability="repo.write",
        required_permission="repo.write",
    )
    assert ticket["state_epoch"] == 7
    validate_plugin_dispatch_ticket(
        ticket,
        records,
        chat_id="chat-a",
        project_id="project-a",
        repo_scope="owner/repo#main",
        current_state_epoch=7,
    )

    expect(
        PermissionError,
        lambda: validate_plugin_dispatch_ticket(
            ticket, records, chat_id="chat-b", project_id="project-a",
            repo_scope="owner/repo#main", current_state_epoch=7,
        ),
    )
    expect(
        PermissionError,
        lambda: validate_plugin_dispatch_ticket(
            ticket, records, chat_id="chat-a", project_id="project-b",
            repo_scope="owner/repo#main", current_state_epoch=7,
        ),
    )
    expect(
        PermissionError,
        lambda: validate_plugin_dispatch_ticket(
            ticket, records, chat_id="chat-a", project_id="project-a",
            repo_scope="owner/other#main", current_state_epoch=7,
        ),
    )
    expect(
        PermissionError,
        lambda: validate_plugin_dispatch_ticket(
            ticket, records, chat_id="chat-a", project_id="project-a",
            repo_scope="owner/repo#main", current_state_epoch=8,
        ),
    )

    disabled = [record(enabled=False, ready=False)]
    expect(
        PermissionError,
        lambda: validate_plugin_dispatch_ticket(
            ticket, disabled, chat_id="chat-a", project_id="project-a",
            repo_scope="owner/repo#main", current_state_epoch=7,
        ),
    )

    reconnected = [record(permissions=["repo.read"])]
    expect(
        PermissionError,
        lambda: validate_plugin_dispatch_ticket(
            ticket, reconnected, chat_id="chat-a", project_id="project-a",
            repo_scope="owner/repo#main", current_state_epoch=7,
        ),
    )

    changed_capabilities = [record(capabilities=["repo.read"])]
    expect(
        PermissionError,
        lambda: validate_plugin_dispatch_ticket(
            ticket, changed_capabilities, chat_id="chat-a", project_id="project-a",
            repo_scope="owner/repo#main", current_state_epoch=7,
        ),
    )

    expect(
        PermissionError,
        lambda: issue_plugin_dispatch_ticket(
            records, chat_id="chat-a", project_id="project-a", repo_scope="owner/repo#main",
            state_epoch=7, plugin_id="github", capability="repo.write",
            required_permission="admin.write",
        ),
    )
    expect(
        PermissionError,
        lambda: issue_plugin_dispatch_ticket(
            records, chat_id="chat-a", project_id="project-b", repo_scope="owner/repo#main",
            state_epoch=7, plugin_id="github", capability="repo.write",
        ),
    )

    tampered = deepcopy(ticket)
    tampered["capability"] = "repo.read"
    expect(
        ValueError,
        lambda: validate_plugin_dispatch_ticket(
            tampered, records, chat_id="chat-a", project_id="project-a",
            repo_scope="owner/repo#main", current_state_epoch=7,
        ),
    )

    expanded = deepcopy(ticket)
    expanded["access_token"] = "forbidden"
    expect(
        ValueError,
        lambda: validate_plugin_dispatch_ticket(
            expanded, records, chat_id="chat-a", project_id="project-a",
            repo_scope="owner/repo#main", current_state_epoch=7,
        ),
    )

    expect(
        ValueError,
        lambda: issue_plugin_dispatch_ticket(
            records, chat_id="chat-a", project_id="project-a", repo_scope="owner/repo#main",
            state_epoch=0, plugin_id="github", capability="repo.write",
        ),
    )

    print("plugin dispatch authority regressions: ok")


if __name__ == "__main__":
    main()
