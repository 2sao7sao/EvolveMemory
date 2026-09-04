# EvolveMemory Next Development Spec v0.1

## Core Positioning

EvolveMemory is the memory control plane for AI personalization: it decides what to remember, how to store, when to use, how to use, when to suppress, and how to turn memory uncertainty into dynamic interaction.

## North Star

> Continuously reduce the intervention cost users pay to make a system understand them, while preserving user control over privacy, memory, outcomes, and high-risk actions.

## Target Architecture (v3)

For the concrete multi-turn read path, see [Conversation Memory Invocation and Use Protocol](conversation-memory-invocation-spec.md) (Chinese discussion draft, 2026-09-04). It specifies direct recent context, older/cross-thread evidence, query construction, scoped retrieval, profile/event/hypothesis use conditions, budgets, and slice acceptance gates. Its parameters and proposed interfaces are not implemented defaults. The module statuses below describe individual modules; they do not establish end-to-end integration. See section 13 of the new draft for the `c628f00` runtime gaps.

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

```text
1. LLM extraction (provider-backed)
2. Authority & scope resolver             ✓ implemented
3. Temporary vs global preference guard   ✓ implemented (ephemeral_only)
4. Staleness lifecycle                    ✓ implemented
5. Memory interaction controls            ✓ implemented
6. User governance UX
7. Hybrid retrieval (embeddings + reranker)
8. Production hardening (auth, encryption, tenant isolation)
```

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

## PR Sequence

See the full spec for detailed PR descriptions and acceptance criteria:

- PR 0: Positioning & Prototype Boundary ✓
- PR 1: Gate Decision Rules Doc ✓
- PR 2: LLM Extractor Provider Interface (next)
- PR 3: Extraction Eval v2
- PR 4: Authority & Scope Resolver ✓
- PR 5: Write Governance v3 ✓
- PR 6: Cross-Session Storage
- PR 7: Hybrid Retrieval Provider
- PR 8: Staleness & Lifecycle Engine ✓
- PR 9: Event Skills + Procedural Memory
- PR 10: Memory Interaction Layer ✓
- PR 11: Governance Client Flow
- PR 12: Live LLM Demo
- PR 13: Security Hardening
- PR 14: Eval Dashboard
