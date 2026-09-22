# Captain OSS sandbox follow-up — 2026-09-22

Status: research/parking only; no third-party code installed or executed. Local Captain integration remains unverified while the authorized laptop is offline.

## New material finding

Daytona should not currently be promoted as Captain's preferred self-hosted/open-source sandbox dependency without a fresh upstream/license/maintenance verification. September 2026 ecosystem reporting conflicts with older material: recent sources report that Daytona's production code moved closed-source/froze its public implementation in June 2026, while older/current secondary pages still describe it as open source. Treat this conflict as a maintenance/supply-chain risk and re-check official upstream before any adoption.

## Candidate ranking for Captain

1. **OpenHands — evaluate as a builder/coding subsystem, not a router.** Mature autonomous software-development workflow and sandbox-oriented architecture. Potential value: repo-aware plan/build/test/debug loops. Integration rule: Captain remains the sole user-facing control-plane and issues a scoped authority envelope; do not import OpenHands memory/router semantics wholesale.
2. **E2B — evaluate only as an optional remote sandbox adapter.** Firecracker microVM isolation is attractive for untrusted generated code, but it is a hosted/paid dependency in common deployment modes. It must remain opt-in, never silently consume credits, and cannot be required for core local Captain functionality.
3. **OpenCode/Codex CLI — evaluate as optional coding-agent adapters.** Useful mature coding loops; Captain should call them behind the builder boundary rather than stack another top-level orchestrator. Prefer existing subscriptions/local-compatible routes where supported and explicit.
4. **BoxLite / other local microVM sandboxes — research candidate only.** Community reports suggest local microVM isolation without a hosted account, which fits laptop/privacy goals, but maturity/security/Windows support/maintenance must be verified from official upstream before any install.
5. **Daytona — HOLD pending official re-verification.** Conflicting 2026 information about open-source/self-host status means no install/integration decision should rely on old claims.

## Non-negotiable adapter boundary

Any sandbox/builder adapter must receive only a short-lived Captain-issued authority envelope bound to `chat_id + project_id + repo_scope_hash + state_epoch + builder_session_id`. It must not become a second persistent memory/control-plane. Files, preview, console, task output, repository writes and publication must be revalidated against the current epoch before exposure or commit. Credentials stay outside Project Memory, prompts, task payloads and logs. Paid/hosted adapters remain disabled until explicitly connected/enabled by the user in Captain Settings.

## Next local verification slice

When the Captain laptop returns: reconcile the Project Memory epoch contract first, implement its stale-read/stale-write/context-injection regressions against the real memory/context code, run Doctor/router/OpenBuilder regressions, then inspect the real builder adapter seam before choosing any sandbox dependency. Do not install candidates merely to experiment.
