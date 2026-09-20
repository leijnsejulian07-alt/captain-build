# Captain OSS scan — 2026-09-21

Context: both authorized Captain machines were offline at this checkpoint, so this is reversible continuity/research only. No third-party code was installed or executed and no local verification is claimed.

## Highest-value findings

### OpenAgentd — study/adapt selectively, do not replace Captain
- Local desktop cockpit with workspace-aware coding, git worktrees, visible files/diffs, persistent editable memory, provider switching, scheduled tasks and local telemetry.
- Strong fit as a UX/architecture reference for Captain's builder pane, inspector, worktree lifecycle, memory UI and observability.
- Integration rule: borrow/adapt bounded components or patterns only; Captain remains the sole user-facing orchestrator/control-plane.
- Before any code reuse: verify exact license/version, dependency tree, security boundaries and resource cost.

### Limboo — strong reference for resume/revalidation
- Session-centric repo/branch/chat/terminal/checkpoint/memory workspace.
- Especially useful pattern: on resume, revalidate repository state and hand the agent a structured repo delta rather than trusting stale transcript state.
- Candidate Captain capability: epoch-bound `resume_delta` generated from bounded git metadata/files/symbols, scoped to chat_id + project_id + repo_scope + builder_session_id + state_epoch.
- Prefer implementing/adapting the small resume-delta seam rather than importing another orchestrator.

### Agor — observability/governance reference
- Branch-scoped environments, durable session history, per-prompt token/cost accounting, RBAC/ACL concepts and isolated dev servers.
- License is BSL 1.1 per current public project description, so treat as reference unless license review explicitly approves reuse.
- Useful Captain ideas: scoped execution ledger, visible cost/provider/model attribution, dev-server port ownership tied to builder scope.

### Daytona — hosted sandbox adapter only; do not base Captain core on old OSS runtime
- Current docs describe isolated stateful sandboxes and snapshots, but the former open-source runtime moved core development private in June 2026 and the public runtime is frozen.
- Therefore downgrade the old OSS Daytona runtime as a direct integration candidate. A future hosted adapter may remain optional if user explicitly configures/authenticates it and spend controls are enforced.
- No silent paid API use.

### E2B — optional external sandbox adapter candidate
- Current material shows application-managed sandbox lifecycle and one-sandbox-per-chat patterns.
- Potential fit behind Captain's sandbox interface, but external auth/cost/network trust means optional only, never a required core dependency.

## Recommended next implementation after local runtime returns
1. Persist Builder-pane phase state scoped by all five walls and restore it only when the exact scope fingerprint matches.
2. Add a bounded `resume_delta` contract: repo HEAD/base, changed paths, dependency-manifest hashes and optionally symbol-index delta; reject stale epoch/session state.
3. Surface validation receipt freshness and execution/model attribution in the builder inspector.
4. Add regressions proving pane/resume state cannot cross chat/project/repo/session/epoch boundaries.
5. Keep sandbox providers behind one Captain adapter interface; local existing execution remains default. External E2B/Daytona-style providers must be explicitly connected/enabled and pass health/auth/spend gates.

## Safety / architecture decision
Do not add a second router, daemon or autonomous control-plane. Do not execute repo-authored commands merely to compute resume state. Use argv-bounded git/file inspection and fail closed when scope or epoch is missing/mismatched.
