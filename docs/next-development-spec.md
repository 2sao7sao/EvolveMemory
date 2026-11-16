# EvolveMemory Next Development Spec v0.2

Updated 2026-11-16. Product choices are confirmed; the controls and scope slice is being implemented. This document does not establish that the full conversation runtime is complete.

## Core Positioning

EvolveMemory is the memory control plane for AI personalization: it decides what to remember, how to store, when to use, how to use, when to suppress, and how to turn memory uncertainty into dynamic interaction.

## North Star

> Continuously reduce the intervention cost users pay to make a system understand them, while preserving user control over privacy, memory, outcomes, and high-risk actions.

## Target Architecture (v3)

For the concrete multi-turn read path, see [Conversation Memory Invocation and Use Protocol](conversation-memory-invocation-spec.md) (Chinese protocol draft v0.2, updated 2026-11-16). The user has selected project-task continuation, authorized reuse within the same project, personal-profile adaptation only after confirmation, per-event opt-in follow-ups, and conditional source hints. Numerical budgets and the full proposed interfaces remain unvalidated. Section 13 separates the historical `c628f00` gaps from the master read-opt-out and migration-clock fixes already merged in PR #13 at `main@3aa4285`, the current implementation slice, and remaining work. Module availability below does not establish end-to-end integration.

```text
User Turn / App Event / UI Feedback
        ↓
TurnPreprocessor
        ↓
LLM Proposal Extractor + Rule Fallback
        ↓
Authority & Scope Resolver          ← NEW
        ↓
Write Governance Engine (v3)
        ↓
Normalized Memory Store
        ↓
Lifecycle / Staleness Engine         ← NEW
        ↓
Hybrid Retriever
        ↓
Memory Use Gate
        ↓
Response Policy Compiler
        ↓
Memory Interaction Layer             ← NEW
        ↓
Prompt-safe Context + Dynamic Controls + Audit Trace
```

## Key Design Decisions

1. **Memory ≠ just prompt context.** Output includes `interaction_controls` alongside `prompt_context`.
2. **User said ≠ user authorized permanent storage.** Authority model distinguishes explicit commands from inferences.
3. **Cold-start and mature-phase are the same system at different states.** Controls evolve from explore → confirm → exception.
4. **Intervention reduction must be measurable.** Core metric: repeat-task intervention decrease ≥ 30% between sessions 1–3 and 10+.

## Development Priority

| Slice | Deliverable | Acceptance boundary |
| --- | --- | --- |
| Existing baseline fixes | v2 master read opt-out and deterministic migration clock | Already merged in PR #13; retain those regressions. |
| S0-a | Normalized-only v2 reads/writes with shared persisted controls; explicit legacy migration | Existing records/new writes respect disabled keys/layers/features; actual review markers and per-event opt-in are verified independently. No implicit legacy fallback or dual-write. |
| S0-b | Persist and propagate scope/project/domain/authority | Reload tests, permitted same-project reuse, cross-project exclusion, exact unbound-identifier semantics, and explicit migration compatibility. |
| S0-c | Turn-local restrictions and temporary scope | Current-turn overrides do not silently become long-term/global preferences; a request can narrow existing access, never expand it. |
| S1-a | Minimal host adapter and captured model-call input | Inspect the actual package delivered to a deterministic callable; compilation alone is not delivery, and a fake callable is not a live provider. |
| S1-b | Bounded project-task continuation | Preserve recent turns, recover an older decision with sources, and apply current-turn overrides. |
| S2–S4 | Complete cross-thread retrieval, governed feedback, providers, and quality/performance evaluation | Independent evidence for history coverage, authorization, model behavior, latency, cost, and user experience. |

The [controls/scope implementation slice (PR #15)](https://github.com/2sao7sao/EvolveMemory/pull/15) passed 115 local tests (72 pytest subtests), all 11 deterministic eval suites, and the standalone adaptive replay on 2026-11-16. This covers S0-a/S0-b behavior and temporary-ingest protections; S0-c, concurrent revocation/full dependency invalidation, S1 delivery, and real-provider validation remain incomplete. S1-a is brought forward as the first delivery seam. PR #15 is merged at `8e3ab17` and its [hosted CI passed](https://github.com/2sao7sao/EvolveMemory/actions/runs/43906016401). Protocol section 13 records the slice and evidence; a module checkmark does not establish the remaining protocol.

## Key Metrics

| Metric | Target |
| --- | --- |
| Extraction slot F1 | ≥ 0.85 |
| Temporary-to-global error | ≤ 3% |
| Third-party confusion rate | ≤ 2% |
| Gate action accuracy | ≥ 0.85 |
| Sensitive prompt leakage | ≤ 0.5% |
| Stale direct-use rate | ≤ 2% |
| Correction residue rate | ≤ 2% |
| Interaction acceptance rate | ≥ 40% |
| Intervention reduction (sessions 10+) | ≥ 30% |
| Downstream helpfulness delta | ≥ +10% |

## Module Status

These are existing module-level statuses, not completion of the integrated S0/S1 path or the newly confirmed product defaults.

| Module | Status | Location |
| --- | --- | --- |
| Authority Resolver | Implemented | `memory_system/governance/authority.py` |
| Scope Resolver | Implemented | `memory_system/governance/scope.py` |
| Write Governance v3 | Implemented (ephemeral_only, negative_preference) | `memory_system/writing.py` |
| Interaction Controls | Implemented | `memory_system/interaction/controls.py` |
| Intervention Decider | Implemented | `memory_system/interaction/intervention_decider.py` |
| Staleness Engine | Implemented | `memory_system/lifecycle/staleness.py` |
| LLM Extractor (provider-backed) | Interface only | `memory_system/extraction.py` |
| Hybrid Retrieval (embeddings) | Interface only | Future PR |
| User Governance UX | Not started | Future PR |
| Security Hardening | Not started | Future PR |

## Delivery boundaries

The earlier numbered work-package list was a design sequence, not the repository's actual GitHub PR numbering. The current [PR #12](https://github.com/2sao7sao/EvolveMemory/pull/12) is the conversation-protocol draft; [PR #13](https://github.com/2sao7sao/EvolveMemory/pull/13) delivered targeted maintenance fixes, not security hardening.

Use the slices above and the fixed F01–F10 / H01–H04 matrix in the [protocol](conversation-memory-invocation-spec.md) for the next changes. Preserve separate results for local contract tests, captured host delivery, hosted CI, real-provider calls, and user acceptance. Complete cross-thread history and real-model helpfulness remain future work.
