# EvolveMemory Design Review And Iteration Roadmap

Date: 2026-05-02

This document reviews the current system against the original product idea:

```text
what to remember
how to remember
how to use memory to make answers more personally adaptive
```

## 1. Current Fit Against The Original Design

### 1.1 What To Remember

Original intent:

- Events: what happened and how it evolves.
- States: static, semi-static, and fluid user state.
- Psychological profile: inferred understanding of the user from dialogue.
- Interests: long-term and short-term interests.

Current implementation:

- Fact/state memory exists through `MemoryItem`, `MemoryRecord`, and `MemorySlotRegistry`.
- Explicit preferences are supported and strongly influence response policy.
- Profile inference exists, but is still deterministic and narrow.
- Event memory exists and now has the first event skill through `CareerEventSkill`.
- Sensitivity is represented through tags and Phase 2 `Sensitivity`.

Gap:

- The system still relies mostly on rule extraction.
- Profile is not yet a real psychological model with evidence accumulation.
- Event memory has one career skill only; learning, project, life, and relationship events are not implemented.
- Interest memory lacks frequency tracking, decay, and recency scoring.

### 1.2 How To Remember

Original intent:

- Use a state-machine style design.
- Clearly separate mutually exclusive states from coexisting states.
- Keep dynamic and static states separate.
- Make memory correctable.

Current implementation:

- `exclusive_group`, `coexistence_rule`, `valid_from`, and `valid_to` support state lifecycle.
- Correction and retirement APIs exist.
- `MemoryStore` uses active-time windows instead of deleting history.
- Phase 2 `MemoryRecord` adds status, version, supersession, authority, sensitivity, and allowed use.
- `NormalizedSQLiteMemoryRepository` adds normalized records, evidence, audit tables, and operation application.
- `WeightedMemoryWriteEvaluatorV2` and `MemoryOperationPlanner` add deterministic write-governance planning.
- v2 ingest now connects preprocessing, proposal extraction, write planning, normalized persistence, and career event detection.
- v2 query now prefers normalized records when available.
- User settings, normalized delete, forget-all, review queue, and event state persistence now exist as APIs.

Gap:

- Supersession is now applied in normalized storage, but review responses do not yet expose rich before/after diffs.
- Legacy session payload persistence is still maintained for Phase 1 compatibility.
- There is no migration CLI yet.
- Review queue table and approve/reject API exist, but there is no settings UI or batch review workflow yet.
- Sensitive field encryption and retention policy are not implemented.

### 1.3 How To Use Memory

Original intent:

- The most important point is not memory storage, but using memory to make model answers feel better adapted to the user.
- The system should infer cognitive and communication preferences.
- Answers should adapt based on user profile, profession, prior behavior, and current state.

Current implementation:

- `MemoryUseGate` is the main differentiator.
- Gate actions now include `use_directly`, `style_only`, `follow_up`, `clarify`, `hidden_constraint`, `summarize_only`, and `suppress`.
- `ContextCompiler` separates direct facts, style policy, event follow-up cues, hidden constraints, and clarification prompts.
- `ResponsePolicyEngine` converts memory into tone, detail level, structure, decision mode, pace, empathy, and follow-up style.
- Prompt context explicitly tells the downstream model how memory is allowed to influence the answer.

Gap:

- Query intent classification and retrieval planning exist as deterministic rules, but not yet as learned or embedding-backed retrieval.
- Hybrid retrieval with embeddings is not implemented.
- Gate thresholds are hardcoded, not learned or user-configurable.
- The system does not yet evaluate downstream answer quality.
- There is no policy-conditioned answer generator yet.

## 2. Current Code Review Findings

### P1: Phase 2 Runtime Still Needs Governance UX And Hardening

The v2 ingest path now connects:

```text
TurnPreprocessor
-> Rule/LLM proposal extractor
-> WeightedMemoryWriteEvaluatorV2
-> MemoryOperationPlanner
-> NormalizedSQLiteMemoryRepository
```

Operations that require confirmation are now stored in a review queue and can
be approved or rejected through API. Memory settings, single-record delete,
forget-all, and event state APIs also exist. The remaining P1 gap is governance
UX and hardening: batch review, explanations, normalized correction, retention,
and export need to be exposed together.

### P1: User Governance Is Still Incomplete

The system has correction, retirement, settings APIs, sensitivity, review queue,
single-record tombstone delete, and forget-all. It still lacks:

- review suggestions with explanations
- settings UI / client flow
- normalized correction endpoint
- audit export

This is the biggest product gap before the system feels controllable to users.

### P2: Event Memory Needs More Domain Skills

`CareerEventSkill` proves the event-state-machine direction, but the original design
requires event memory to be a general mechanism. Next skills should be:

- `learning_event_skill`
- `project_event_skill`
- `life_event_skill`
- `relationship_event_skill` with stricter privacy gates

### P2: Profile Inference Is Too Shallow

Current profile dimensions are useful but narrow. The next version should accumulate
evidence and expose user-readable explanations:

```text
profile dimension
-> supporting evidence
-> confidence history
-> decay / reinforcement
-> user correction
```

### P2: Eval Coverage Is Still Too Small

The first `gate_eval` smoke test is useful, but not sufficient. The next eval sets
should cover:

- extraction quality
- write decision quality
- contradiction and supersession
- privacy leakage
- event status transition
- prompt context compilation

## 3. Recommended Next Iteration Order

1. Add normalized correction endpoint and before/after review diffs.
2. Add embedding provider interface and hybrid retrieval.
3. Add LLM proposal extractor interface with JSON validation and repair.
4. Add more event skills.
5. Add migration CLI from legacy session payloads to normalized records.
6. Add sensitive field encryption and retention enforcement.
7. Add audit export and batch review workflows.
8. Expand eval harness from smoke tests to quality metrics.
9. Add downstream answer-quality evals.
10. Add UI examples for settings, review queue, and memory inspection.

## 4. Summary

EvolveMemory is now meaningfully differentiated from a normal vector memory store.
Its strongest design point is:

```text
retrieval is not usage
```

The system is increasingly aligned with the original vision, especially in memory
use governance and response policy compilation. The main remaining work is not
another layer of documentation; it is integrating the Phase 2 runtime path end to
end and giving users governance over what is remembered and how it is used.
