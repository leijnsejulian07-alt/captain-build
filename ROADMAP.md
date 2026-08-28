# Captain — Complete Roadmap / TODO

> Central backlog for Captain. GitHub is the parking/fallback layer; the live local Captain workspace remains the source of truth when the laptop is available.

## Status snapshot

- Beast Build core: ~80–85% complete.
- Architecture: single Captain control plane/router.
- Security model: fail-closed, scoped by chat + project + repo where applicable.
- Main remaining work: controlled authority expansion, richer research/connectors, safer real build/test execution, deeper multi-agent orchestration, UX/polish and final hardening.

---

## P0 — Finish current parked work

- [ ] Apply research → Project State bridge locally.
- [ ] Persist only distilled research metadata: queries, title, canonical URL, provider, retrieval timestamp, matched queries/corroboration, score, source/host counts.
- [ ] Never persist snippets, raw provider responses, page text/HTML, cookies/tokens, chat_id, preview/builder/worktree state or generated conclusions from untrusted snippets.
- [ ] Require valid `project_id + repo_scope`; otherwise persist nothing.
- [ ] Drop invalid/non-http(s) sources before persistence.
- [ ] Ensure persistence failure never breaks the user-visible research response.
- [ ] Keep Project State secret-value redaction authoritative.
- [ ] Run metadata-only persistence smoke test.
- [ ] Run secret-redaction test.
- [ ] Run same-project/different-repo isolation test.
- [ ] Run unscoped-no-persistence test.
- [ ] Run persistence-failure-preserves-result test.
- [ ] Compile changed modules.
- [ ] Run router regression.
- [ ] Run isolated capability/plugin/connector regressions.
- [ ] Restart through normal launcher and run Doctor.
- [ ] Roll back on any failed acceptance gate.

## P0 — Safe real build/test runner

- [ ] Define explicit allowlisted build/test profiles instead of arbitrary commands.
- [ ] No free terminal/shell execution from Captain.
- [ ] Add profile detection for common repo types without auto-executing scripts.
- [ ] Add explicit `process:bounded` permission checks.
- [ ] Add explicit network permission policy for build/test jobs; default deny where practical.
- [ ] Keep secret-scrubbed child-process environment.
- [ ] Use native Windows Job Objects kill-on-close for all spawned process trees.
- [ ] Keep full process-tree cleanup fallback.
- [ ] Add hard timeout per profile.
- [ ] Add bounded stdout/stderr capture.
- [ ] Use isolated worktree as execution root.
- [ ] Use reserved per-worktree runtime port slots.
- [ ] Detect filesystem mutations before/after validation/build/test.
- [ ] Refuse or flag unexpected writes outside allowed workspace/worktree.
- [ ] Add Python/pytest profile only after authority boundaries are green.
- [ ] Add npm test/build profile only after authority boundaries are green.
- [ ] Add framework-specific profiles gradually, never arbitrary package scripts by default.
- [ ] Add clean success/failure/timeout/mutation result schema for UI/reviewer.
- [ ] Add hostile-input tests for command injection and repo-script abuse.

## P0 — Isolation/security finalization

- [ ] Re-run full cross-chat isolation suite.
- [ ] Re-run full cross-project isolation suite.
- [ ] Re-run full cross-repo isolation suite.
- [ ] Verify task control requires matching chat/project/repo scope.
- [ ] Verify preview ownership remains chat + project + repo scoped.
- [ ] Verify worktree ownership remains chat + project + repo scoped.
- [ ] Verify Project State remains project + canonical repo scoped.
- [ ] Verify memory namespace cannot collide across same-named files/repos.
- [ ] Verify protected directories remain inaccessible through local tools and previews.
- [ ] Verify symlink/junction/reparse-point escape defenses.
- [ ] Verify no credential-like values can persist in Project State.
- [ ] Verify subprocess environments cannot inherit provider/API secrets.
- [ ] Verify execution audits do not leak raw local repo paths.
- [ ] Add authority-expansion regression checks inspired by agentdiff-style diffing.
- [ ] Add crash/restart recovery tests for tasks, previews, worktrees and Project State.

## P1 — Research / Agent Reach capability layer

- [ ] Build provider-neutral research-session schema.
- [ ] Persist safe research-session metadata behind Project State boundaries.
- [ ] Add Agent Reach as an adapter/capability source, never as a second control plane.
- [ ] Gate every channel behind Captain permissions.
- [ ] Normalize provenance across Tavily / GitHub / Reddit / YouTube / RSS / X / other channels.
- [ ] Add source URL validation and canonicalization for every adapter.
- [ ] Add host/source diversity limits.
- [ ] Preserve corroboration across multiple queries/providers.
- [ ] Mark external text as untrusted in every channel.
- [ ] Add Reddit research adapter.
- [ ] Add GitHub research adapter.
- [ ] Add YouTube metadata/transcript adapter where legally/technically appropriate.
- [ ] Add RSS adapter.
- [ ] Evaluate X/Twitter adapter with official/safe auth constraints.
- [ ] Evaluate LinkedIn/Bilibili/Xiaohongshu only behind explicit auth/cookie permissions; no silent cookie scraping.
- [ ] Add research-session resume/reopen flow.
- [ ] Add source review UI with provider, timestamp, corroboration and trust boundary.
- [ ] Never auto-promote research findings into executable instructions.

## P1 — Builder / OpenBuilder evolution

- [ ] Keep OpenBuilder adapted behind Captain only.
- [ ] Improve framework/project detection.
- [ ] Improve Builder pane state and session UX.
- [ ] Add safe build-profile selector.
- [ ] Add safe test-profile selector.
- [ ] Add preview health/status checks.
- [ ] Add runtime restart/reconcile controls.
- [ ] Add bounded preview logs with stronger structured event types.
- [ ] Add change review flow before publication/merge.
- [ ] Improve diff visualization.
- [ ] Add snapshot/rollback UX.
- [ ] Keep preview localhost-only by default.
- [ ] Keep directory listing disabled.
- [ ] Keep protected files blocked from preview.
- [ ] Add stale preview/session cleanup.
- [ ] Add framework runtime port mapping to reserved worktree slots.
- [ ] Add explicit publish/deploy gate; never auto-deploy.

## P1 — Worktree / parallel development

- [ ] Improve worktree session status UI: active/stale/missing/dirty.
- [ ] Reconcile stale claims safely.
- [ ] Reconcile orphan runtime port reservations safely.
- [ ] Add session resume/re-attach.
- [ ] Add worker → reviewer handoff metadata.
- [ ] Add clean merge-preparation flow without automatic merge.
- [ ] Add explicit branch cleanup only after clean/reviewed state.
- [ ] Keep max-session limits and resource caps.
- [ ] Add disk-pressure awareness before creating more worktrees.
- [ ] Add automatic safe cleanup suggestions, not destructive cleanup.

## P1 — Multi-agent orchestration

- [ ] Formalize Planner → Builder → Reviewer pipeline.
- [ ] Add isolated parallel workers with separate worktrees/scopes.
- [ ] Add resumable agent sessions.
- [ ] Add bounded heartbeat/claim model for workers.
- [ ] Add reviewer acceptance gates before marking work complete.
- [ ] Add explicit evidence/tests in completion claims.
- [ ] Prevent one agent from controlling another agent's scoped task/session unless authorized.
- [ ] Add concurrency/resource limits for weak laptop hardware.
- [ ] Adapt useful OpenHands / Claw Code / CrewCode patterns without importing a second router.
- [ ] Never enable `--dangerously-skip-permissions` style behavior.

## P1 — Connectors / authenticated integrations

- [ ] Finish central Settings / Connections UX.
- [ ] Connect GitHub through official auth and scoped permissions.
- [ ] Connect Gmail through official auth and scoped permissions.
- [ ] Connect Google Drive through official auth and scoped permissions.
- [ ] Add Calendar/Contacts only when useful and permission-scoped.
- [ ] Finish Computer/cptr → Captain connection through authenticated Admin/Connections UI.
- [ ] Do not bypass auth/session checks to remove Doctor warning.
- [ ] Add connector health checks.
- [ ] Add expired/revoked OAuth notice flow.
- [ ] Add dismissible but recurring notices for broken credentials.
- [ ] Add setup-version verification/promotion only after successful test.
- [ ] Add per-project connector permission boundaries where applicable.
- [ ] Never log tokens/cookies/authorization headers.

## P1 — Provider/router improvements

- [ ] Keep `/v1/models` exposing only Captain as the user-facing model.
- [ ] Improve free/local-first routing policy.
- [ ] Add provider health scoring and cooldowns.
- [ ] Add rate-limit/failure-aware fallback behavior.
- [ ] Keep provider secrets loaded only through existing encrypted secret loader.
- [ ] Never silently consume paid APIs.
- [ ] Surface which route/provider was used without exposing secrets.
- [ ] Validate every provider before marking it working.
- [ ] Keep xAI/Grok disabled from automatic routing while validation still fails.
- [ ] Re-check Cloudflare Workers AI before enabling.
- [ ] Re-check Kimi/Cohere/etc. periodically.
- [ ] Add per-provider cost/free-tier metadata and hard policy controls.
- [ ] Add optional user preference for local-only / free-cloud / explicitly-approved-paid.

## P1 — Chat / memory / Project State

- [ ] Improve persistent chat recovery after browser/router restart.
- [ ] Add chat rename/archive/search UX.
- [ ] Keep delete confirmation and server+browser deletion consistent.
- [ ] Improve task completion notifications without duplicates.
- [ ] Add safe distilled global learning layer separate from repo-specific memory.
- [ ] Define exactly what may graduate from project memory to global memory.
- [ ] Never globally persist raw repo content/secrets/private project-specific state.
- [ ] Add Project State schema/versioning/migrations.
- [ ] Add bounded history for selected Project State fields where useful.
- [ ] Add Project State inspection UI.
- [ ] Mark stored text as context, never executable instruction/permission.

## P1 — Task/background system

- [ ] Improve recurring-task management UI.
- [ ] Add pause/resume/edit recurring task controls.
- [ ] Add clear next-run/run-count/deadline display.
- [ ] Add task retry policy with bounded attempts.
- [ ] Add crash-safe job claims.
- [ ] Add stale claim recovery.
- [ ] Add per-project concurrency limits.
- [ ] Add clearer blocked/failed/completed status reasons.
- [ ] Keep task ownership scoped by chat/project/repo.
- [ ] Add safe notification summary back to owning chat.

## P2 — UX / productization

- [ ] Refine Captain UI to feel consistently ChatGPT-like without duplicating control planes.
- [ ] Improve sidebar/project/chat organization.
- [ ] Add project switcher with visible repo scope.
- [ ] Add model/router status panel.
- [ ] Add Tools & Connectors status panel polish.
- [ ] Add permissions explanation and one-click revoke.
- [ ] Add Builder session overview.
- [ ] Add preview/worktree/task status badges.
- [ ] Improve errors into short user-actionable messages.
- [ ] Add dark/light/system appearance support if not already fully wired.
- [ ] Improve responsive/mobile layout where useful.
- [ ] Keep desktop one-button flow: shortcut → start/check services → Captain opens.
- [ ] Remove/avoid advanced setup from normal daily usage.

## P2 — Launcher / reliability / operations

- [ ] Keep one desktop shortcut as primary entry point.
- [ ] Verify launcher idempotently starts/checks Ollama, cptr, router and worker.
- [ ] Improve startup race handling and readiness waits.
- [ ] Add service restart/reconcile controls in advanced settings.
- [ ] Add single-instance protections everywhere needed.
- [ ] Add bounded structured logs with secret redaction.
- [ ] Add backup rotation policy.
- [ ] Add restore-from-last-known-good workflow.
- [ ] Add disk monitoring and keep ≥8 GB safety gate.
- [ ] Only clean reproducible caches automatically/safely.
- [ ] Never touch user-marked review/archive folders without approval.
- [ ] Add long-running soak test for router/worker/task persistence.

## P2 — Security hardening

- [ ] Fuzz/hostile-input tests for router endpoints.
- [ ] Test oversized body limits everywhere.
- [ ] Test malformed JSON everywhere.
- [ ] Test path traversal on every filesystem endpoint.
- [ ] Test symlink/junction escapes on every file-serving surface.
- [ ] Test permission downgrade/revoke while session is active.
- [ ] Test connector auth expiry/revocation.
- [ ] Test secret-like data in titles, queries, filenames and metadata.
- [ ] Test malicious web snippets attempting prompt/tool injection.
- [ ] Test malicious repo instructions attempting scope escape.
- [ ] Test arbitrary package scripts cannot run outside allowlisted profiles.
- [ ] Test child-process orphan resistance.
- [ ] Test network-denied build/test behavior.
- [ ] Test unexpected filesystem mutation detection.
- [ ] Add security regression suite to every acceptance cycle.

## P2 — Power Hunt / capability research

- [ ] Continue daily GitHub/Reddit/etc. capability hunt.
- [ ] Evaluate tools as ADAPT / IDEA_ONLY / REJECT / INTEGRATE.
- [ ] Prefer MIT/Apache/BSD-compatible building blocks where practical; review copyleft obligations before copying code.
- [ ] Adapt patterns instead of blindly installing full orchestrators.
- [ ] Never add a second primary router/control plane.
- [ ] Track useful OpenHands patterns.
- [ ] Track Claw Code / UltraWorkers patterns.
- [ ] Track CrewCode/crew worktree/reviewer patterns.
- [ ] Track Cate session/editor/browser patterns.
- [ ] Track Prime Agent resumable-goal patterns.
- [ ] Track agentdiff regression/security patterns.
- [ ] Track lightweight Windows isolation/process supervision improvements.
- [ ] Re-evaluate heavier sandbox/micro-VM options only if hardware/cloud resources improve.

## P3 — Optional later capabilities

- [ ] Optional stronger sandbox/container/micro-VM execution for untrusted builds.
- [ ] Optional cloud execution workers when laptop constraints become limiting.
- [ ] Optional remote Captain access with proper authentication/TLS; never expose current localhost services directly.
- [ ] Optional richer artifact generation/editing integrations.
- [ ] Optional deployment adapters (e.g. Vercel/Replit) behind explicit publish permission.
- [ ] Optional team/multi-user boundaries if Captain becomes shared.
- [ ] Optional mobile companion/remote status surface.

---

## Definition of Done — Beast Build core

Captain core is considered complete only when:

- [ ] Single Captain control plane remains intact.
- [ ] Chat/project/repo isolation passes hostile tests.
- [ ] Secrets cannot leak through storage, logs, tools, subprocesses or previews.
- [ ] Research persistence is metadata-only and provenance-bearing.
- [ ] Real build/test execution is allowlisted, bounded and contained.
- [ ] Builder preview/worktrees/tests/review form one safe flow.
- [ ] Multi-agent workers are isolated and reviewer-gated.
- [ ] Major connectors use official authenticated flows.
- [ ] Router is free/local-first and never silently spends paid API credits.
- [ ] One-button startup works reliably.
- [ ] Core regressions are green.
- [ ] Doctor core is green.
- [ ] Remaining warnings are genuinely optional and documented.
- [ ] Backups/rollback exist for every material change.
- [ ] No completion claim is made without test evidence.

## Current immediate order

1. Research → Project State bridge.
2. Safe allowlisted real build/test profiles.
3. Agent Reach / richer research adapters.
4. Builder + worktree + reviewer flow refinement.
5. Multi-agent orchestration.
6. Authenticated connectors.
7. Provider/routing hardening.
8. UX/productization.
9. Full hostile-input + soak acceptance.
10. Continuous Power Hunt and capability adaptation.
