# Captain OSS scout — 2026-09-15 Copilot SDK follow-up

Fresh follow-up while B310 is offline. No third-party code was installed or executed.

## GitHub Copilot SDK — promising optional coding-agent adapter
- Official GitHub announcement (2026-06-02): SDK is GA and exposes planning, tool invocation, file edits, streaming and multi-turn sessions.
- Integration features include custom tools/MCP, pre/post tool hooks, permission-request hooks, OpenTelemetry tracing, OAuth/GitHub App auth and BYOK.
- GitHub says it is available to existing Copilot subscribers including Copilot Free, or via BYOK; Captain must still never assume entitlement or activate paid usage silently.
- Fit: potentially high-value as an optional repo-aware coding/build engine behind Captain, especially because hooks can enforce Captain-owned project/repo/epoch authority and approvals at every tool boundary.
- Control-plane rule: do not adopt the SDK's orchestration/model selection as Captain's primary router. If prototyped, Captain creates a scoped adapter session, supplies only approved tools/context, owns persistent memory/job state, and validates every mutation/output before commit/preview/apply.
- Auth: expose through canonical Captain Settings. Prefer official GitHub OAuth/GitHub App flows; never invent tokens or silently reuse unrelated credentials.
- Resource cost: likely materially heavier than Captain's deterministic local contracts because it launches/embeds an agent runtime. Benchmark startup latency, idle RAM/CPU and session cleanup on B310 before enabling.
- Decision: candidate for a narrow opt-in adapter proof-of-concept after local reconciliation, not a replacement for OpenBuilder or Captain routing.

## GitHub Remote MCP Server — GitHub connector implementation option
- GitHub's remote MCP server is GA with OAuth 2.1 + PKCE and short-lived/refreshable credentials.
- GitHub has sunset Copilot Extensions in favor of MCP, making MCP the safer forward-compatible integration surface.
- GitHub also supports MCP allowlist governance and secret-scanning tooling in supported environments.
- Fit: strong implementation option for Captain's GitHub connector behind the existing plugin/settings/dispatch authority. Captain should allowlist tool families and permissions per project/repo instead of exposing the entire server ambiently.
- Decision: prefer official OAuth MCP over PAT-based bespoke GitHub auth when Captain's runtime compatibility and resource tests are green.

## Architecture takeaway
1. Keep Captain as the single control-plane and persistent memory authority.
2. Treat Copilot SDK as an optional coding-agent backend and GitHub MCP as an optional connector backend.
3. Require existing plugin dispatch tickets plus exact chat/project/repo/epoch validation before either subsystem receives context or tool authority.
4. Keep OpenBuilder as Captain's builder abstraction; backend selection must be replaceable and must not leak backend-native session state across projects.
5. Do not enable either candidate until B310 local Doctor/isolation/resource/security tests pass.
