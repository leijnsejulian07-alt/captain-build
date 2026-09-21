# Captain connector/settings research checkpoint — 2026-09-21

Status: parking only; no third-party code executed or installed.

## Findings

### GitHub MCP Server — strong direct-adapter candidate
- Official GitHub project, MIT licensed, actively maintained.
- Remote MCP supports OAuth; local stdio also supports browser OAuth with PKCE and keeps the resulting token in memory rather than writing it to disk.
- PAT remains available but should be secondary in Captain UI; permissions must remain explicit.
- Fit: high. Prefer adapter behind Captain's existing control-plane, not another router/daemon.
- Captain UX implication: Settings should expose auth method, permissions/toolsets, health, and a first-class Connect/Reconnect action. Never display/log token material.

### MCP/hosted connector patterns
- Current MCP ecosystem increasingly uses OAuth and explicit authorization/scopes. Provider migrations are real: Atlassian documents legacy endpoint migration and auth/client-cache remediation.
- Captain therefore needs connector health to distinguish auth validity from provider/version migration state instead of reducing everything to connected=true/false.

## Proposed canonical state machine
Installed = adapter/component is present.
Connected = provider/session credentials are successfully associated.
Enabled = user permits Captain to use it.
Ready = Installed + Connected + Enabled + healthy auth/provider state.
Permissions = explicit granted/selected capabilities; not inferred from Ready.

Persist only non-secret health metadata. Credential material belongs in OS/provider-approved secret storage or official OAuth/session machinery.

## Notification behavior
Important unresolved states (expired/invalid auth, migration required, provider deprecation) produce a safe persistent notice with a Settings deep-link. Dismissal sets only a reminder time; it never marks the issue resolved. A later launch/health check re-surfaces after the reminder interval. Successful health checks clear the notice automatically. Notice text must not contain tokens, account secrets, raw auth headers, or sensitive provider payloads.

## Integration order when local runtime returns
1. Reconcile `connector_state_contract.v1.json` with existing connector registry/settings model.
2. Add state-machine regressions, including Ready fail-closed invariants.
3. Add health-check adapter interface with redacted results only.
4. Add canonical Settings cards + Connect/Test Connection/Enable/Permissions actions.
5. Add persistent remediation notices scoped to connector + user/workspace, never project content.
6. Run Doctor/router/settings regressions and verify no paid provider is invoked implicitly.
