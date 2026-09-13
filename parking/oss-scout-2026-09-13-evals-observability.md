# Captain OSS scout — evals, observability, durable jobs — 2026-09-13

This follow-up intentionally avoids re-evaluating the builder/sandbox candidates already covered in today's other scout notes. No third-party code was installed or executed.

## 1. OpenTelemetry GenAI conventions — adopt as Captain's telemetry contract

Sources: https://opentelemetry.io/blog/2026/genai-observability/ and https://opentelemetry.io/docs/specs/

OpenTelemetry now has concrete GenAI attributes for model identity, token usage and finish reasons, while its agent conventions continue to evolve. This is a strong fit because Captain can emit vendor-neutral spans from its single control-plane instead of embedding a proprietary observability backend.

Decision: **high priority adapter/contract**. Instrument Captain router, tool, research, builder and background-job boundaries behind one optional OTel exporter. Keep export disabled/local by default. Never record prompts, tool arguments/results, memory contents, connector credentials or other content attributes by default; content capture must be explicit and separately permissioned. Scope identifiers should be hashed/pseudonymized before export. The exporter must never become execution authority.

Community signal: recent LocalLLaMA/MLOps/Observability discussions repeatedly favor OTel context propagation over hand-rolled parent/child tracing, while also warning that traces alone do not detect silent semantic failures. Treat this as supporting evidence, not an authority source.

## 2. Inspect AI — strong optional evaluation subsystem, not a router

Sources: https://inspect.aisi.org.uk/ and https://github.com/UKGovernmentBEIS/inspect_ai

Inspect is maintained by the UK AI Security Institute and Meridian Labs, is MIT licensed, has an active public repository, and exposes reusable datasets/agents/tools/scorers plus sandboxing, tool approvals, log viewing and external-agent bridges. Its documented checkpointing is especially relevant to long-running Captain acceptance suites.

Decision: **prototype an adapter after local reconciliation**. Use Inspect to run reproducible Captain capability/safety/regression suites against Captain as the system under test. Do not embed Inspect as Captain's production orchestration layer and do not let it bypass Captain's project/repo/epoch or connector permission gates. Benchmark laptop CPU/RAM/disk cost before enabling locally by default.

## 3. Claw-Eval — useful external benchmark/reference, too heavy for core runtime

Source: https://github.com/claw-eval/claw-eval

Claw-Eval is MIT licensed and currently exposes 300 human-verified tasks with completion, safety and robustness rubrics and repeated-trial scoring. It is useful for sampling realistic multi-turn/general-agent acceptance cases.

Decision: **benchmark/reference only for now**. Its sandbox, repeated trials and model-grader requirements can be expensive and are not appropriate for an always-on laptop dependency. Import/adapt selected task ideas only after license/provenance review; do not copy task content blindly.

## 4. Durable queue libraries — do not add a second daemon

Current search surfaced several young SQLite/Postgres queues (Workmatic, PyBgWorker, Workhorse and others). Some have good ideas such as leases/fence tokens and durable progress, but most either add another daemon/broker, are very new, or require PostgreSQL.

Decision: **no direct dependency now**. Captain already needs one control-plane and must stay light on B310. The new stdlib SQLite task-state store on this branch covers restart persistence and generation fencing without a duplicate scheduler. Borrow proven concepts such as lease/fence tokens only where the existing Captain worker ownership model needs them. Workhorse's fence-token documentation is a useful architecture reference, but PostgreSQL is unnecessary for the laptop-first core.

## Acceptance implications

1. Add OTel-compatible trace envelopes only after local runtime reconciliation; exporter off by default and content-free by default.
2. Add deterministic trace IDs tied to safe hashed scope, never raw project/chat/repo identifiers.
3. Evaluate Inspect as an optional CI/eval adapter with Captain remaining the system under test and control-plane.
4. Keep semantic regression tests separate from observability: traces explain failures but do not prove correctness.
5. Keep durable jobs in Captain-owned persistence; no Redis/Postgres/extra daemon solely for queueing on the laptop baseline.
