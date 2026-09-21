# Captain OSS scan — builder/runtime follow-up — 2026-09-21

Context: both authorized Captain machines are offline, so this is reversible GitHub continuity/research only. No third-party code was installed or executed; no local verification is claimed.

## New candidates / decisions

### sandboxd — HIGH priority bounded adapter candidate
Source: https://github.com/tastyeffectco/sandboxd
- MIT, self-hosted, API-first app-builder runtime: isolated Docker sandbox per app, live preview URL, files/git/diffs, process logs, snapshots/fork/restore, task checkpoints and revert.
- Deliberately compact architecture (Go + Docker + Traefik + SQLite) and sleep/wake behavior make it more plausible on a laptop than a Kubernetes-style platform.
- Strong match for Captain's missing builder execution substrate, but it must sit *behind* Captain/OpenBuilder rather than becoming another user-facing orchestrator.
- Security caveat from upstream: beta/0.x; container isolation is not VM isolation; API auth is off by default and hardening is required for untrusted multi-tenancy. Therefore: do not install blindly; pin/review version, bind locally, require Captain scope token/ownership checks, and keep repo/project/epoch/session walls authoritative in Captain.
- Integration preference: adapt the headless /v1 API only. Do not adopt its console as Captain UI. Captain's builder pane should own files/preview/console/diffs/rollback UX and map every sandbox to chat_id + project_id + repo_scope + builder_session_id + state_epoch.
- Credentials must remain in Captain's canonical Settings/secret boundary. Do not copy provider secrets into project state or logs. No paid provider activation by default.

### Limboo — architecture/reference remains useful, not a second control plane
Source: https://github.com/limboo-ai/limboo
- Local-first workspace around coding agents with repo indexing, git/worktrees, terminal, durable project memory, permissions and provider-neutral adapters.
- Especially valuable design principle: one authorization core across providers and an OS-level sandbox floor. Study permission/risk-class/path-guard patterns; do not import its orchestration layer wholesale.

### Claudable / Bolt Builder — UI references, lower integration priority
Sources: https://github.com/anymorph-ai/Claudable and https://github.com/bolt-builder/builder
- Useful references for chat-first builder UX, integrated editor/terminal/live preview and provider-neutral agent invocation.
- They overlap heavily with Captain/OpenBuilder's user-facing role; direct adoption risks duplicate orchestration. Prefer bounded UI/pane patterns only after license/dependency review.

### Celesto — WATCH as stronger isolation option
Source: https://github.com/CelestoAI/celesto
- Apache-2.0 persistent agent-computer runtime with snapshot/restore and Firecracker on Linux / QEMU on macOS.
- Potential future hardened sandbox backend when container isolation is insufficient, but likely heavier than sandboxd for the current Windows laptop path. Keep behind the same Captain sandbox adapter interface if evaluated later.

## Proposed Captain adapter contract (do not implement against live runtime until local reconciliation)
`BuilderRuntimeAdapter` should expose only bounded lifecycle primitives: create(scope), inspect(scope), run_task(scope, plan), files(scope), logs(scope), preview(scope), diff(scope), checkpoint(scope), rollback(scope, checkpoint), stop(scope). Every call must carry and revalidate the exact five-wall fingerprint; adapter-native IDs are never sufficient authority.

Runtime capabilities must be declared rather than assumed: isolation_level, live_preview, snapshots, rollback, git, max_concurrency, network_policy, secret_injection_mode, version, health. Captain chooses a runtime through the existing single router/control-plane and must fail closed if capability/health/scope requirements are unmet.

## Next local acceptance work
1. Reconcile this proposal against Captain's actual OpenBuilder/runtime interfaces; reuse existing primitives instead of creating parallel ones.
2. Implement a no-op/fake adapter first and regress all five scope walls, ownership, epoch invalidation, rollback ownership and preview-port ownership.
3. Only after those tests pass, consider a pinned sandboxd proof-of-concept behind an explicit experimental toggle in Captain Settings.
4. Run Doctor/router/OpenBuilder/memory regressions and measure idle RAM/CPU + cold start before enabling it by default.

## Rejection rules
Reject or park any runtime that needs a second router/daemon as authority, cannot enforce Captain ownership boundaries, leaks credentials into sandboxes/logs, requires silent paid API use, or materially degrades normal-chat laptop performance.
