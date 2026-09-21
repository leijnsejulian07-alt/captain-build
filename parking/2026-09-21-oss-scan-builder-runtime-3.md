# Captain OSS scan — builder/runtime delta — 2026-09-21

Context: authorized Captain laptop is still unreachable. This run inspected the current captain-build continuity state first. No third-party code was installed or executed and no local verification is claimed.

## New candidate: Singulary — WATCH / UI+runtime reference
Source: https://github.com/sammwyy/singulary

- MIT, self-hosted AI app builder with Docker workspaces, full-stack edit/run/debug loops and snapshot/revert semantics.
- Relevant because its feature shape overlaps Captain's desired Builder pane: agent-driven file changes, execution, preview and reversible changes.
- Do **not** adopt it as Captain's orchestrator: that would duplicate Captain/OpenBuilder's control plane. If reviewed further, mine bounded runtime/preview/snapshot patterns or expose only a narrow adapter beneath Captain.
- Security/resource review required before any execution: inspect image pinning, network defaults, host mounts, Docker socket exposure, secret handling, process limits and Windows/Docker Desktop idle cost.

## New candidate: Capka — architecture reference only
Community source: https://www.reddit.com/r/OpenSourceAI/comments/1wa2kgi/a_selfhosted_ai_agent_workspace_where_every_chat/

- Interesting design signal: isolated persistent Linux workspace per chat, durable server-side tasks, MCP tools and provider controls.
- Captain should **not** copy the per-chat-only authority model. Captain's stricter five-wall fingerprint (chat_id + project_id + repo_scope + builder_session_id + state_epoch) remains authoritative because a chat can outlive/switch project state.
- Useful reference for durable workspace UX and reconnect/resume behavior, but early/solo-project maturity means no direct integration priority without upstream/license/security verification.

## Updated runtime priority
1. Keep `sandboxd` as the leading bounded-runtime PoC candidate: API-first, compact, MIT, preview/snapshot/diff primitives already align with the adapter contract.
2. Keep stronger microVM backends (e.g. E2B-style/Firecracker candidates) as a future hardened option; do not add cloud spend or heavy infra merely for isolation while local Builder integration is incomplete.
3. Treat Singulary/Capka as pattern sources unless a later audit finds a clearly superior narrow subsystem.
4. Avoid Kubernetes-oriented sandbox stacks on the current laptop path unless Captain later needs server-scale concurrency; they add operational/resource cost without solving the immediate desktop integration gap.

## Acceptance implication
Before integrating any real runtime, Captain must prove the fake adapter contract for: five-wall authorization on every operation, epoch invalidation, bounded files/logs/checkpoints, secret-safe observability, preview ownership, rollback ownership, and stopped-session non-resurrection. A real adapter must not weaken these semantics even if the backend exposes a reusable native sandbox ID.
