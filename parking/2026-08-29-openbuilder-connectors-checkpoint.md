# Captain OpenBuilder + connectors checkpoint — 2026-08-29

Local laptop work completed before Remote Desktop became temporarily unreachable:

- Backed up Captain connector/builder files under `Backups/captain-openbuilder-connectors-20260829-1900`.
- Upgraded the OpenBuilder bridge to use OpenBuilder's native `generate()` path rather than DOM textarea/submit injection.
- OpenBuilder now returns scoped `request_id`, success/failure, file count and generated project files to Captain; Captain matches the result to the initiating chat/project/repo before applying it.
- Captain-side OpenBuilder repo synchronization is enabled through the existing scoped Builder Workspace gate; `builder-workspace` was granted `repo:write` in the local plugin config in response to the user's explicit request to make OpenBuilder fully operational. Scope remains fail-closed.
- OpenBuilder TypeScript typecheck and production build were green before dependency cleanup. Native live integration smoke was green (`OPENBUILDER_NATIVE_LIVE_SMOKE_OK`).
- Removed temporary OpenBuilder `node_modules` and pruned caches after building. Free disk recovered to about 9.34 GB during the run.
- GitHub connector backend was changed so Connect launches an official interactive flow rather than merely printing a command. It can install GitHub CLI via winget when missing and then launch `gh auth login --hostname github.com --git-protocol https --web` in a separate console. Test still verifies with `gh auth status`; credentials are never captured by Captain.
- Because the machine-level winget install stalled, a portable official GitHub CLI 2.98.0 archive was downloaded from the official `cli/cli` GitHub release and extracted under `Tools/Connectors/GitHub/bin/gh.exe`. Connector status was locally verified as Installed=true, Connected=false, health=auth_required, version `gh version 2.98.0 (2026-08-20)`.
- GitHub plugin was enabled locally with `git:remote` permission. No GitHub login was performed automatically; the user must still press Connect and complete official OAuth.
- Captain Settings connector UI was updated so pending connectors do not present a misleading working Connect button; GitHub's launched auth/install flow is automatically polled and re-tested when connection becomes available.
- Gmail and Drive remain intentionally fail-closed because their local OAuth adapters are not yet implemented; no fake login or borrowed credentials were added.

Important local follow-up once Remote Desktop is reachable again:

1. Compile Python files and syntax-check Captain JS.
2. Restart the router with existing secret loader.
3. Verify `/captain/plugins` shows Builder Workspace `repo:write`, GitHub Installed=true/Enabled=true, Gmail/Drive truthful adapter-pending state.
4. Run GitHub connector action smoke without completing login: status/test must fail cleanly as auth_required; user-facing Connect should launch the official OAuth flow.
5. Run OpenBuilder scoped start/status/stop + result-sync smoke and router regression/Doctor.
6. Do not mark Gmail/Drive as connected until real official OAuth adapters exist.
