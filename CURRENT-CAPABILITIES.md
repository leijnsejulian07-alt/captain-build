# Captain — Current Capabilities Inventory

Last verified from the live laptop acceptance log: 2026-08-28.

This document records what is already implemented/proven so the roadmap does not accidentally rebuild completed work. `ROADMAP.md` is the forward backlog; this file is the current-state inventory.

## Architecture / control plane
- Captain is the single primary custom control plane/router; no stacked external orchestrator is required.
- One visible model name: `captain`.
- Local Qwen/Ollama fallback plus cloud-provider pool/failover.
- One-click Windows desktop launcher starts/checks the workspace and opens Captain.
- Advanced maintenance menu remains separate.

## Scope and isolation
- Explicit `chat_id + project_id + repo_scope` boundaries.
- Background task listing/control is full-scope gated and fails closed.
- Explicit invalid/non-local repo scopes do not fall back to the full AI Workspace.
- Project State is keyed by project + canonical repo-scope hash.
- Project memory namespace avoids same-filename cross-repository collisions.
- Builder previews are isolated by full chat/project/repo scope.
- Worktree sessions are isolated by full scope.

## Chat / UI
- Captain browser UI served locally.
- Persistent browser + disk-backed chat history.
- New chat and delete-chat flow.
- Project/repository scope persisted with chats.
- Active-task sidebar with pause/resume/stop controls.
- Scoped task completion/failure/blocked updates return to the owning chat.
- Per-task notification cursor prevents missed or duplicate terminal updates.
- Text/code attachments supported.
- PNG/JPEG/WebP/GIF image attachments supported through verified Gemini vision routing; image bytes are not persisted in chat history.
- Tools & Connectors / Settings visibility with readiness/state information.

## Background work
- Persistent task queue and worker.
- Job schema includes goal, instruction, deadline, priority, workspace/project scope, retry cap.
- Explicit recurring tasks (`every N minutes/hours/days`) with >=15-minute floor.
- Recurrence preserves scope and deadline semantics.
- Windows-safe atomic queue persistence.

## Memory / Project State
- Raw history and distilled memory separated.
- Memory dedupe by fingerprint and write audit trail.
- Credential-like memory content rejected.
- Persistent Project State with atomic writes and bounded payloads.
- Project State sensitive field-name filtering.
- Project State credential-like value redaction even under innocent field names.
- Scoped Project State can be injected into ordinary Captain LLM routes as bounded non-executable context.
- Builder -> Project State bridge stores only distilled activity metadata (last operation/file/activity/coarse preview status), not contents/diffs/ports/chat IDs.
- Worktree -> Project State metadata bridge exists.

## Deterministic local tools
- Workspace/Captain status.
- Scoped Git status.
- Recent Git commits/log.
- Git diff/stat/changed-files view.
- Bounded text-file read (128 KB max).
- Bounded directory listing.
- Scoped repository text/code search.
- Protected directories such as Secrets/.ssh/.gnupg denied.
- Heavy/generated directories skipped where appropriate.
- Child-process environments scrub API keys/tokens/password-like variables.

## Repomix
- Audited adapter uses Repomix through `npx.cmd` without requiring a global install.
- Scoped `repo context` / `repomix` command.
- Requires valid local Git repository scope and permissions.

## Research / web
- Tavily-backed bounded web-search tool.
- Search text treated as untrusted external data.
- HTTP(S)-only result URL validation; unsafe schemes dropped.
- Source provenance: provider, score, UTC retrieval time, title and URL.
- Multi-query research bundles (max 3 queries).
- Canonical URL deduplication.
- Cross-query corroboration retained/ranked.
- Maximum two returned sources per host for diversity.
- Up to ten diverse normalized sources.
- Raw snippets remain explicitly marked untrusted.
- Pending P0: safely bridge bounded research provenance/metadata into Project State without persisting raw snippets/provider responses/secrets/chat IDs.

## Builder / OpenBuilder adaptation
- OpenBuilder is adapted behind Captain rather than installed as a second router/control plane.
- Builder subsystem/capability broker uses least privilege and progressive completion gates.
- Scoped file-tree UI.
- Existing editor/diff/rollback workflow.
- Local static preview start/status/reconcile/stop.
- Preview binds to `127.0.0.1` only and uses ephemeral ports.
- Preview permission `preview:local` is default-deny.
- Sandboxed preview iframe.
- Bounded per-scope preview console/logs.
- Preview query strings stripped from activity logs.
- Dotfiles/protected paths/directory listing denied.
- Windows symlink/junction/reparse traversal hardened and regression-tested.

## Git worktree sessions
- Isolated worktree-session manager.
- Separate `git:worktree` permission, default off.
- Unique branch + checkout per session.
- Maximum 8 live sessions per scope.
- UI flow: Create session -> Open -> Review -> Clean.
- Open creates a new Captain chat scoped to the worktree.
- Review shows bounded Git status + staged/unstaged diff.
- Dirty cleanup is refused.
- No automatic merge, push or branch deletion.
- Managed-path checks prevent arbitrary cleanup.
- `last_seen_at` ownership/heartbeat metadata with active/stale/missing state.

## Parallel runtime isolation primitives
- Each worktree receives an atomically reserved localhost block of 8 ports.
- Port reservations are bounded and scoped.
- Transactional creation rolls back reservation/worktree state on failure.
- Orphan runtime-slot reconciliation only reclaims slots when no valid session owns them and the entire port block is free.

## Bounded validation / process safety
- Managed-worktree-only bounded validator.
- Python AST/syntax validation.
- JavaScript `node --check` validation.
- Separate `process:bounded` permission, default off.
- 30-second timeout and 24 KB output cap.
- Secret-scrubbed environment.
- Validation runs outside the worktree and checks Git status before/after for mutations.
- Native Windows Job Object supervisor with kill-on-close containment.
- Process-group + tree-kill fallback retained.
- Adversarial tests proved timed-out and clean-parent-exit child processes do not remain orphaned.
- Arbitrary repo scripts / free terminal / unrestricted `npm test` or pytest remain intentionally blocked pending filesystem + network authority bounding.

## Permissions / execution gate
- Capability/plugin execution gate with explicit grants.
- Least-privilege operation-level authorization.
- Default-deny for higher-authority capabilities such as preview, worktrees and bounded processes.
- Execution audit includes non-reversible repo-scope hash rather than leaking the local path.
- Temporary smoke-test permissions are restored/revoked after tests.

## Connectors
- Connector framework and health/settings layer.
- State distinguishes Installed / Connected / Enabled / Ready / Permissions.
- Persistent remediation notices with temporary dismissals.
- GitHub/Gmail/Drive are not falsely marked connected when official auth/runtime prerequisites are absent.
- Auth/session bypasses are explicitly not used.
- Remaining known optional acceptance warning: Computer/cptr -> Captain must be saved through its authenticated Admin/Connections UI.

## Provider routing
- Local Qwen/Ollama fallback.
- Lazy cloud adapters/provider pool architecture.
- Previously live-validated providers include OpenRouter, Cerebras, Mistral, Hugging Face and Gemini.
- Gemini vision route supports image turns.
- Provider failures rotate/fallback rather than breaking the single Captain model abstraction.
- xAI/Grok remains quarantined because its validation returned HTTP 400; it is not auto-routed or falsely marked working.
- Paid APIs are not supposed to be silently consumed for acceptance smokes.

## Reliability / safety
- Atomic persistence used for important local state.
- Rollback backups are made before risky changes.
- Doctor/regression gates are used after changes.
- Existing >=8 GB free-disk safety gate; safe cleanup previously restored free disk from ~6.85 GB to ~8.43 GB using reproducible npm cache only.
- Secrets/project data/backups/manual-review archive areas were not blindly deleted.
- Protected local secret directories remain inaccessible to normal Captain file tools.

## Regression / acceptance coverage already proven
Examples of named acceptance smokes/regressions already recorded locally:
- `ROUTER_REGRESSION_OK`
- `FULL_SCOPE_WALL_LIVE_OK`
- `PROJECT_STATE_LIVE_OK`
- `PROJECT_STATE_RUNTIME_SCOPE_OK`
- `PROGRESSIVE_SUBSYSTEM_LEAST_PRIVILEGE_OK`
- `STATIC_PREVIEW_BACKEND_OK`
- `LIVE_STATIC_PREVIEW_OK`
- `PREVIEW_FULL_SCOPE_ISOLATION_OK`
- `LIVE_PREVIEW_FULL_SCOPE_ISOLATION_OK`
- `LIVE_PREVIEW_CONSOLE_OK`
- `PREVIEW_JUNCTION_HARDENING_OK`
- `LIVE_PREVIEW_JUNCTION_HARDENING_OK`
- `BUILDER_PROJECT_STATE_BRIDGE_OK`
- `LIVE_BUILDER_PROJECT_STATE_BRIDGE_OK`
- `WORKTREE_ISOLATION_SMOKE_OK`
- `LIVE_WORKTREE_ISOLATION_OK`
- `LIVE_WORKTREE_REVIEW_UI_BACKEND_OK`
- `LIVE_WORKTREE_UI_OK`
- `WORKTREE_RUNTIME_SLOTS_OK`
- `LIVE_WORKTREE_RUNTIME_SLOTS_OK`
- `BOUNDED_VALIDATION_SMOKE_OK`
- `LIVE_BOUNDED_VALIDATION_OK DEFAULT_DENY CROSS_SCOPE_DENY`
- `RUNTIME_SLOT_RECONCILE_OK`
- `PROCESS_TREE_CONTAINMENT_OK`
- `WINDOWS_JOB_OBJECT_CONTAINMENT_OK`
- `RESEARCH_PROVENANCE_SMOKE_OK`
- `RESEARCH_BUNDLE_SMOKE_OK`
- `RESEARCH_DIVERSITY_SMOKE_OK`
- `PROJECT_STATE_VALUE_REDACTION_OK`
- `LIVE_PROJECT_STATE_VALUE_REDACTION_OK`

## Power-hunt / evaluated references
Captain's local research log has already evaluated patterns from OpenBuilder, OpenHands, Goose, Aider, Plandex, UltraWorkers/Claw Code, Agent Reach, BrowserCode/browser-use, sandboxd, ShipIt, office/document MCP candidates, SmolVM, Ephemeral Sandbox, AgentScope, Prime Agent, agentdiff, CrewCode/crew, Cate, Rove, falq, processkit-py, HyperAgent and others.

Policy: adapt useful patterns/components behind Captain. Do not blindly install a second router/control plane or weaken Captain's scope/permission boundaries.

## Current highest-priority gaps
See `ROADMAP.md`. The most immediate known gap is the fail-closed research bundle -> Project State provenance bridge. After that, the largest safety-critical block is bounded real build/test execution with explicit allowlists plus filesystem/network authority controls.

## Source of truth note
This is an inventory/hand-off document, not a replacement for live verification. Before claiming a feature still works, use the live Captain acceptance/Doctor/regression gates. Do not infer that an old PASS guarantees current runtime health.