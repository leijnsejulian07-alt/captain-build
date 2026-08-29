# Captain fallback proposal — Agent Skills adapter (2026-08-29)

Status: design-only fallback; laptop was reported online but Remote Desktop filesystem call returned `Not connected`, so nothing here is claimed locally integrated.

## Candidate
Adopt the open Agent Skills (`SKILL.md`) format as Captain's generic reusable-skill interchange layer, behind Captain's existing single control-plane. The upstream format is Apache-2.0 and uses progressive disclosure: discover metadata first, load full instructions/resources only when relevant.

## Why this fits Captain
- Avoids hard-coding project-specific behavior while making reusable capabilities portable.
- Low runtime cost: plain folders/Markdown plus optional scripts/resources; no second router/daemon.
- Can coexist with Captain's existing plugin settings: `Installed`, `Enabled`, `Ready`, permissions and health remain Captain-owned state.
- Progressive disclosure reduces context pressure versus injecting every skill into every chat.

## Fail-closed adapter contract
Each activation must carry `chat_id`, `project_id`, and `repo_scope`. A skill may be global only if its manifest declares it project-agnostic and contains no project memory. Project-local skills resolve only from the active project/repo roots. Never search another project's skill directory as fallback. Scripts are disabled by default; executable skills require explicit capability permissions and sandbox/policy approval. Treat downloaded skill instructions as untrusted content until reviewed; never allow a skill to override Captain's auth, secret, isolation, paid-API, or control-plane policies.

## Proposed manifest state
Captain should index: `id`, `name`, `description`, `source`, `source_version`, `license`, `installed`, `enabled`, `ready`, `permissions`, `scope`, `content_hash`, `last_validated_at`, `health`, `update_available`. Settings owns enable/disable and permission controls. Activation logs skill id/version/hash but never secret values or private file contents.

## Acceptance tests before local enablement
1. Global harmless skill activates in two projects without sharing project state.
2. Project-local skill from project A is invisible in project B.
3. Missing/invalid scope fails closed.
4. Script-bearing skill cannot execute without declared + granted permission.
5. Disabled skill cannot activate even when semantically matched.
6. Content hash/version change invalidates prior readiness until revalidated.
7. Malicious instructions requesting secret/auth bypass are rejected.
8. Skill discovery metadata does not load full skill bodies into normal-question context.

## Decision
High-value next integration candidate. Prefer implementing a small native Captain adapter/parser and validator rather than installing a community skill manager. Do not auto-install community skills. E2B was also reviewed as a future sandbox option, but it requires an API key/cloud dependency (or heavy self-hosting), so it is lower priority for this laptop-first build.