from __future__ import annotations

from parking.integration.plugin_dispatch_authority import issue_plugin_dispatch_ticket
from parking.integration.plugin_dispatch_runtime import PluginDispatchRuntime


def record(**overrides):
    row = {
        "schema_version": 1, "plugin_id": "github", "installed": True,
        "connected": True, "enabled": True, "ready": True, "auth_method": "oauth",
        "scope": "project", "project_id": "project-a",
        "capabilities": ["repo.write"], "permissions": ["repo.write"], "health": "healthy",
    }
    row.update(overrides)
    return row


def expect(exc_type, fn):
    try:
        fn()
    except exc_type:
        return
    raise AssertionError(f"expected {exc_type.__name__}")


def matches(runtime, receipt, operation, **overrides):
    args = {
        "operation_digest": operation,
        "chat_id": "chat-a",
        "project_id": "project-a",
        "repo_scope": "owner/repo#main",
        "current_state_epoch": 9,
        "plugin_id": "github",
        "capability": "repo.write",
    }
    args.update(overrides)
    return runtime.receipt_matches(receipt, **args)


def main():
    records = [record()]
    ticket = issue_plugin_dispatch_ticket(
        records, chat_id="chat-a", project_id="project-a", repo_scope="owner/repo#main",
        state_epoch=9, plugin_id="github", capability="repo.write", required_permission="repo.write",
    )
    operation = "a" * 64
    runtime = PluginDispatchRuntime()
    receipt = runtime.authorize_once(
        ticket, records, chat_id="chat-a", project_id="project-a", repo_scope="owner/repo#main",
        current_state_epoch=9, operation_digest=operation,
    )
    assert receipt["authorized"] is True
    assert matches(runtime, receipt, operation)
    assert not matches(runtime, receipt, "b" * 64)

    # The execution receipt is still bound to the same isolation wall at the
    # side-effect boundary; a digest alone cannot authorize another scope.
    assert not matches(runtime, receipt, operation, chat_id="chat-b")
    assert not matches(runtime, receipt, operation, project_id="project-b")
    assert not matches(runtime, receipt, operation, repo_scope="owner/other#main")
    assert not matches(runtime, receipt, operation, current_state_epoch=10)
    assert not matches(runtime, receipt, operation, plugin_id="builder")
    assert not matches(runtime, receipt, operation, capability="repo.read")

    tampered = dict(receipt)
    tampered["scope"] = {"chat_id": "chat-a", "project_id": "project-a", "repo_scope": "owner/other#main"}
    assert not matches(runtime, tampered, operation)
    malformed = dict(receipt)
    malformed["ticket_digest"] = "not-a-digest"
    assert not matches(runtime, malformed, operation)

    # Side-effect authority is one-shot: retries require a freshly issued ticket.
    expect(PermissionError, lambda: runtime.authorize_once(
        ticket, records, chat_id="chat-a", project_id="project-a", repo_scope="owner/repo#main",
        current_state_epoch=9, operation_digest=operation,
    ))

    # Validation happens before consumption, so stale/cross-scope tickets cannot poison the ledger.
    fresh = issue_plugin_dispatch_ticket(
        records, chat_id="chat-a", project_id="project-a", repo_scope="owner/repo#main",
        state_epoch=9, plugin_id="github", capability="repo.write",
    )
    expect(PermissionError, lambda: runtime.authorize_once(
        fresh, records, chat_id="chat-a", project_id="project-a", repo_scope="owner/repo#main",
        current_state_epoch=10, operation_digest="c" * 64,
    ))
    assert len(runtime.consumed) == 1

    disabled = [record(enabled=False, ready=False)]
    expect(PermissionError, lambda: PluginDispatchRuntime().authorize_once(
        fresh, disabled, chat_id="chat-a", project_id="project-a", repo_scope="owner/repo#main",
        current_state_epoch=9, operation_digest="d" * 64,
    ))

    expect(ValueError, lambda: PluginDispatchRuntime().authorize_once(
        fresh, records, chat_id="chat-a", project_id="project-a", repo_scope="owner/repo#main",
        current_state_epoch=9, operation_digest="not-a-digest",
    ))

    # Receipts contain only scoped metadata/digests, never connector state or secrets.
    assert set(receipt) == {
        "schema_version", "authorized", "ticket_digest", "operation_digest", "scope",
        "state_epoch", "plugin_id", "capability",
    }
    print("plugin dispatch runtime regressions: ok")


if __name__ == "__main__":
    main()
