"""Executable stdlib regressions for connector notice policy parking code."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from connector_notice_policy import notice_for, visible
from connector_readiness import evaluate

NOW = datetime(2026, 9, 22, 20, 0, tzinfo=timezone.utc)
BASE = {
    "connector_id": "github",
    "installed": True, "connected": True, "enabled": True, "auth_method": "oauth",
    "permissions": ["repo:read"],
    "health": {"status": "healthy", "auth_status": "valid", "provider_version_status": "current"},
    "chat_id": "chat-a", "project_id": "project-a", "repo_scope_hash": "sha256:repo-a", "state_epoch": 7,
}

def expect_error(value):
    try:
        notice_for(value, NOW)
    except (ValueError, TypeError):
        return
    raise AssertionError("expected fail-closed rejection")

def main():
    healthy = deepcopy(BASE)
    assert evaluate(healthy)["ready"] is True
    assert notice_for(healthy, NOW) is None

    expired = deepcopy(BASE)
    expired["health"]["auth_status"] = "expired"
    expired["ready"] = True
    assert evaluate(expired)["ready"] is False
    n = notice_for(expired, NOW)
    assert n["code"] == "auth_expired"
    assert n["settings_section"] == "settings/connectors/github"
    assert "repo_scope" not in n
    assert visible(n, now=NOW, chat_id="chat-a", project_id="project-a", repo_scope_hash="sha256:repo-a", state_epoch=7)
    assert not visible(n, now=NOW, chat_id="chat-a", project_id="project-b", repo_scope_hash="sha256:repo-a", state_epoch=7)
    assert not visible(n, now=NOW, chat_id="chat-a", project_id="project-a", repo_scope_hash="sha256:repo-a", state_epoch=8)

    unknown_auth = deepcopy(BASE); unknown_auth["auth_method"] = "future_magic"
    normalized = evaluate(unknown_auth)
    assert normalized["ready"] is False and "auth_method_invalid" in normalized["blockers"]

    assert not visible(n, dismissed_at=NOW, now=NOW + timedelta(hours=23), chat_id="chat-a", project_id="project-a", repo_scope_hash="sha256:repo-a", state_epoch=7)
    assert visible(n, dismissed_at=NOW, now=NOW + timedelta(hours=25), chat_id="chat-a", project_id="project-a", repo_scope_hash="sha256:repo-a", state_epoch=7)

    raw = deepcopy(expired); raw["repo_scope"] = "C:/secret/repo"; expect_error(raw)
    zero = deepcopy(expired); zero["state_epoch"] = 0; expect_error(zero)
    boolean = deepcopy(expired); boolean["state_epoch"] = True; expect_error(boolean)
    partial = deepcopy(expired); partial.pop("repo_scope_hash"); expect_error(partial)

    # Persistent notices must never accept provider-controlled external/open-redirect,
    # traversal, or cross-connector remediation targets.
    external = deepcopy(expired); external["remediation"] = {"settings_section": "https://evil.example/login"}; expect_error(external)
    traversal = deepcopy(expired); traversal["remediation"] = {"settings_section": "settings/connectors/../secrets"}; expect_error(traversal)
    cross_connector = deepcopy(expired); cross_connector["remediation"] = {"settings_section": "settings/connectors/slack/permissions"}; expect_error(cross_connector)
    bad_id = deepcopy(expired); bad_id["connector_id"] = "github/../../secrets"; expect_error(bad_id)
    valid_deep = deepcopy(expired); valid_deep["remediation"] = {"settings_section": "settings/connectors/github/permissions"}
    assert notice_for(valid_deep, NOW)["settings_section"] == "settings/connectors/github/permissions"

    global_connector = deepcopy(expired)
    for key in ("chat_id", "project_id", "repo_scope_hash", "state_epoch"):
        global_connector.pop(key)
    g = notice_for(global_connector, NOW)
    assert visible(g, now=NOW)
    assert not visible(g, now=NOW, chat_id="chat-a", project_id="project-a", repo_scope_hash="sha256:repo-a", state_epoch=7)
    print("connector notice regressions: PASS")

if __name__ == "__main__":
    main()
