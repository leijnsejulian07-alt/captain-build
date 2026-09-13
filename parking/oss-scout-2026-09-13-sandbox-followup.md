# Captain OSS scout follow-up — 2026-09-13

## Scope

Targeted follow-up on sandbox/runtime components that could strengthen Captain's builder loop without creating a second control-plane. No third-party code was installed or executed.

## Findings

### OpenHands Software Agent SDK / Agent Server

Current upstream architecture is a useful reference and potential adapter target. The SDK exposes Python, TypeScript and REST surfaces for coding agents and supports local or ephemeral Docker/Kubernetes workspaces. OpenHands' Agent Canvas deliberately separates UI/control-plane responsibilities from execution/sandbox responsibilities, which matches Captain's requirement that Captain remain the user-facing orchestrator.

Sources:
- https://github.com/OpenHands/software-agent-sdk
- https://github.com/OpenHands/OpenHands
- https://github.com/OpenHands/OpenHands/blob/main/docs/architecture.md

Risks observed in current upstream issues matter for a Windows laptop deployment: browser startup inside the agent-server Docker image has had Chromium sandbox failures, and agent-server webhook failures have caused container crashes / sandbox connection errors. A requested pluggable durable-execution backend also indicates that long-running task durability is not yet something Captain should delegate blindly to OpenHands.

Sources:
- https://github.com/OpenHands/software-agent-sdk/issues/4256
- https://github.com/OpenHands/software-agent-sdk/issues/4245
- https://github.com/OpenHands/software-agent-sdk/issues/4254

**Decision:** keep OpenHands SDK/Agent Server as an evaluated optional builder/sandbox adapter, not Captain's primary router and not a required local dependency yet. If prototyped later, place it behind Captain's existing builder-session, project/repo/epoch, approval and output-handle boundaries. Require a Windows/B310 resource benchmark and failure-injection test before enabling by default.

### Daytona / Nightona lineage

The former open Daytona core is no longer a straightforward dependency choice: a community continuation states that Daytona moved core development private in June 2026 and that the last complete open release was v0.190.0 under AGPL-3.0. Nightona continues that codebase, but AGPL obligations, community-fork maintenance risk and the size of the sandbox stack make direct embedding unattractive for Captain's laptop-first default.

Source:
- https://github.com/nightona-co/nightona

A recent downstream report also highlights an operational lesson independent of provider: rebuilding a sandbox snapshot by deleting the active snapshot first can take an agent runtime down when the replacement build fails.

Source:
- https://github.com/Agenta-AI/agenta/issues/5652

**Decision:** do not embed Daytona/Nightona as Captain's default local sandbox. Preserve provider-neutral sandbox adapters and adopt the operational rule: build/validate a replacement snapshot first, then atomically switch; never destroy the last known-good runtime before the new runtime is healthy.

## Concrete Captain acceptance additions

1. Any optional sandbox adapter must be subordinate to Captain's single control-plane and receive a scope-bound short-lived dispatch authority, never raw global Captain authority.
2. Builder/sandbox tasks must survive UI reconnects through Captain-owned durable task state; adapter process/session state is not the source of truth.
3. A sandbox adapter must prove chat + project + repo + Project State epoch isolation and reject stale-epoch reconnect/resume.
4. Preview URLs, process handles, terminal streams and artifact references are scoped capabilities and must be revoked when the builder session or Project State epoch changes.
5. Runtime-image/snapshot upgrades use create -> health-check -> atomic switch -> retire-old ordering, with rollback to the last known-good version.
6. Default local enablement requires measured idle/active RAM, CPU, disk and startup impact on B310 plus a clean uninstall/disable path.
7. Windows/browser support is a required regression if an adapter exposes browser-backed preview/testing.
8. Paid or hosted sandboxes remain explicit opt-in through canonical Captain Settings; no silent spend or implicit account creation.

## Priority

Near-term priority remains Captain-owned durable task/job state and local reconciliation, not adopting another execution daemon. The OpenHands SDK is worth a later isolated prototype because its API/runtime split is compatible with Captain's adapter model, while Daytona/Nightona is currently better treated as architectural reference or optional remote/self-hosted provider than a laptop default.
