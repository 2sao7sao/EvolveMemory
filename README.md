<img src="assets/adaptive-memory-engine-hero.png" alt="Adaptive Memory Engine banner" width="100%" />

# Adaptive Memory Engine

[![Status](https://img.shields.io/badge/status-Prototype%20%2F%20WIP-yellow)](./README.md)
[![Stars](https://img.shields.io/github/stars/2sao7sao/adaptive-memory-engine?style=flat)](https://github.com/2sao7sao/adaptive-memory-engine)
[![Commit Activity](https://img.shields.io/github/commit-activity/m/2sao7sao/adaptive-memory-engine)](https://github.com/2sao7sao/adaptive-memory-engine/commits/main)
[![License](https://img.shields.io/badge/license-MIT-blue)](./LICENSE)
[![Python](https://img.shields.io/badge/python-3.11%2B-brightgreen)](./requirements.txt)

Adaptive Memory Engine is a user-centric memory system prototype for
conversational AI. It turns dialogue into structured memory, decides what is
worth keeping, and converts active memory into response guidance that helps a
model answer in a way that fits the user.

The core question:

```text
Given what we know about this user, how should the model respond right now?
```

---

## Quick Links

- [TL;DR](#tldr)
- [Vision](#vision)
- [Why](#why)
- [What It Builds](#what-it-builds)
- [Current Architecture](#current-architecture)
- [Memory Layers](#memory-layers)
- [Component Catalog](#component-catalog)
- [Mode Presets](#mode-presets)
- [Spec Gap](#spec-gap)
- [API](#api)
- [Local Development](#local-development)
- [Roadmap](#roadmap)

---

## TL;DR

- A memory engine for conversational AI, not a generic transcript database.
- Four memory layers: `event`, `state`, `preference`, and `profile`.
- Candidate memories are scored before writing through a configurable write policy.
- State memory supports mutual exclusion, coexistence, validity windows, correction, and audit.
- Query-time retrieval produces a response policy instead of dumping all memory into a prompt.
- The current implementation is a working FastAPI prototype with local JSON or SQLite persistence.

---

## Vision

The project is designed around one product belief:

> Personal AI should not only remember facts. It should adapt how it communicates.

Memory is useful only when it changes behavior. A good system should know
whether the user wants direct recommendations, calm explanation, dense detail,
minimal follow-up, or a slower step-by-step discussion. Those response choices
should be grounded in remembered events, current states, preferences, and
revisable profile signals.

Current status: **Prototype / WIP**.

---

## Why

Most memory systems stop at storage and retrieval:

- They keep facts but do not decide whether a fact is worth keeping.
- They retrieve memory but do not convert it into answer behavior.
- They blur stable facts, short-lived states, preferences, and inferred profile traits.
- They have weak correction paths when the system remembers something wrong.
- They rarely explain why a memory was written, rejected, retired, or merged.

Adaptive Memory Engine treats memory as an operational loop:

```text
remember -> validate -> retrieve -> adapt response -> accept correction -> audit
```

---

## What It Builds

The current prototype includes:

- raw Chinese dialogue extraction
- structured LLM extraction payload parsing
- declarative memory slot registry
- write scoring before persistence
- memory store with exclusive/coexisting memory behavior
- active-memory validity windows
- user correction and memory retirement
- audit events for memory lifecycle changes
- profile inference from preferences and states
- query-aware retrieval
- response policy generation
- model-ready prompt context
- FastAPI service endpoints
- local JSON or SQLite persistence
- demo and unit tests

---

## Current Architecture

<img src="assets/architecture.svg" alt="Adaptive Memory Engine architecture" width="100%" />

```mermaid
flowchart TD
    A["Dialogue turn or structured LLM extraction"] --> B["Candidate memory extraction"]
    A --> R["MemorySlotRegistry"]
    B --> C["MemoryWriteEvaluator"]
    C -->|accepted| D["MemoryStore"]
    C -->|rejected| E["Audit: reject"]
    D --> F["ProfileInferencer"]
    F --> D
    D --> G["QueryMemoryRetriever"]
    G --> H["ResponsePolicyEngine"]
    H --> I["PromptContextBuilder"]
    I --> J["Model-ready prompt context"]
    D --> K["DiskSessionRepository"]
    D --> N["SQLiteSessionRepository"]
    D --> L["Correction / retirement API"]
    L --> D
    L --> M["Audit: correct / retire"]
```

Runtime flow:

```text
ingest
  -> extract candidates
  -> score write decisions
  -> write accepted memories
  -> reject low-value candidates with audit events
  -> infer profile dimensions
  -> persist session

query
  -> load active memories
  -> retrieve query-relevant memory
  -> build response policy
  -> optionally assemble prompt context
```

---

## Memory Layers

### Events

Events describe things that happened and may shape future context.

Examples:

- changed jobs
- broke up
- moved cities
- started preparing for an exam
- recently began learning skiing

Events are time-sensitive. They often create or update states, and they are
useful for follow-up support.

### States

States describe what is true about the user now.

State dynamics:

- `static`: stable facts, such as education level
- `semi_static`: facts that change occasionally, such as relationship status or work status
- `fluid`: short-lived context, such as being anxious, busy, or preparing for interviews

State relationship rules:

- mutually exclusive: only one active value should exist in an exclusive group
- coexisting: multiple values can be active at the same time
- time-bound: fluid states should naturally expire or be retired

### Preferences

Preferences describe how the user wants to be served.

Examples:

- direct communication
- concise answers
- conclusion first
- step-by-step explanation
- fewer follow-up questions
- stronger recommendations

This is the shortest path from memory to better answers.

### Profile

Profile memory is inferred from dialogue and preference history. It is not a
rigid personality label. It is a set of revisable dimensions with confidence
and evidence.

Current dimensions:

- `structure_preference_level`
- `directness_preference_level`
- `detail_tolerance`
- `emotional_support_need`
- `pace_preference`

---

## Component Catalog

| Component | File | Responsibility |
| --- | --- | --- |
| `MemoryItem` | `memory_system/schema.py` | Normalized memory record with confidence, validity, coexistence, source, and audit metadata. |
| `WriteDecision` | `memory_system/schema.py` | Records write score, threshold, factors, and final write decision. |
| `MemoryAuditEvent` | `memory_system/schema.py` | Explains writes, merges, rejections, retirements, and corrections. |
| `ResponsePolicy` | `memory_system/schema.py` | Compact answer-control object used by the model-facing layer. |
| `SlotDefinition` | `memory_system/registry.py` | Declarative definition for one memory slot: type, dynamics, exclusivity, TTL, scoring weights, and sensitivity. |
| `MemorySlotRegistry` | `memory_system/registry.py` | Central registry of supported memory slots and their default rules. |
| `DialogueMemoryExtractor` | `memory_system/engine.py` | Rule-based Chinese dialogue extractor for the current prototype. |
| `MemoryWriteEvaluator` | `memory_system/engine.py` | Scores candidate memories before persistence. |
| `MemoryStore` | `memory_system/engine.py` | Applies active-memory, merge, retirement, correction, and audit rules. |
| `ProfileInferencer` | `memory_system/engine.py` | Infers user profile dimensions from active states and preferences. |
| `QueryMemoryRetriever` | `memory_system/engine.py` | Retrieves memories relevant to the current user query. |
| `ResponsePolicyEngine` | `memory_system/engine.py` | Converts memory signals into response policy. |
| `StructuredMemoryParser` | `memory_system/structured.py` | Parses LLM-produced JSON extraction payloads into `MemoryItem` objects. |
| `PromptContextBuilder` | `memory_system/prompting.py` | Builds model-ready prompt context from relevant memory and policy. |
| `SessionRepository` | `memory_system/persistence.py` | Storage interface shared by JSON and SQLite repositories. |
| `DiskSessionRepository` | `memory_system/persistence.py` | Persists session memory and audit events to local JSON files. |
| `SQLiteSessionRepository` | `memory_system/persistence.py` | Persists session memory and audit events to a local SQLite database. |
| `SessionMemoryRuntime` | `memory_system/service.py` | Orchestrates extraction, scoring, storage, inference, retrieval, and prompt context. |
| FastAPI app | `app.py` | Provides HTTP endpoints for integration. |
| Demo CLI | `demo.py` | Runs the memory loop locally with sample turns. |

---

## Data Model

Each memory item uses a normalized schema:

```json
{
  "type": "state",
  "key": "relationship_status",
  "value": "single",
  "confidence": 0.92,
  "source": "turn_4",
  "evidence": "我现在单身",
  "valid_from": "2026-04-16T09:00:00+08:00",
  "valid_to": null,
  "confirmed_by_user": true,
  "exclusive_group": "relationship_status",
  "coexistence_rule": "mutually_exclusive",
  "dynamics": "semi_static",
  "tags": [],
  "last_updated": "2026-04-16T09:00:00+08:00"
}
```

Important fields:

- `type`: `event`, `state`, `preference`, or `profile`
- `key`: normalized semantic slot
- `value`: normalized slot value
- `confidence`: confidence in `[0, 1]`
- `source`: turn, model, or correction source
- `evidence`: text or reason supporting the memory
- `valid_from` and `valid_to`: active time window
- `exclusive_group`: conflict group for mutually exclusive memories
- `coexistence_rule`: how the memory interacts with nearby memories
- `dynamics`: stability class

---

## Write Policy

Not every extracted detail should become long-term memory. Candidate memories
are scored before they are written:

```text
memory_value = stability * reuse * personalization_gain * confidence
```

The current `MemoryWriteEvaluator` returns a `WriteDecision`:

```json
{
  "should_write": true,
  "score": 0.641,
  "threshold": 0.16,
  "reason": "passes write policy",
  "factors": {
    "stability": 0.92,
    "reuse": 0.95,
    "personalization_gain": 0.98,
    "confidence": 0.75
  }
}
```

High-value examples:

- stable user facts
- repeated preferences
- major life events
- active work or emotional context
- guidance preferences that influence future answers

Low-value examples:

- one-off throwaway remarks
- weak guesses
- details with low future reuse
- transient facts that do not affect response quality

---

## State Machine Rules

The store uses active-time windows rather than deleting history. Slot defaults
come from `MemorySlotRegistry`, so common state-machine behavior is now
declared centrally instead of being only embedded in extraction logic.

Mutually exclusive examples:

- `relationship_status`: `single`, `dating`, `married`
- `education_level`: `associate`, `bachelor`, `master`, `phd`
- `detail_preference`: `concise`, `detailed`
- `response_opening`: `answer_first`

Coexisting examples:

- `interest_long_term`
- `interest_short_term`
- `response_opening=answer_first` with `explanation_structure=step_by_step`
- multiple life events over time

When a new memory enters the same exclusive group, the previous active memory is
retired by setting `valid_to`. A memory is active only when `valid_to` is empty
or later than the current timestamp.

---

## Mode Presets

<img src="assets/mode_matrix.svg" alt="Adaptive Memory Engine mode matrix" width="100%" />

The prototype can be reasoned about through operational modes:

```text
observe  -> extract candidates without assuming all are worth keeping
write    -> score, accept, reject, merge, or retire memories
retrieve -> select only query-relevant memories
adapt    -> convert relevant memory into response policy
correct  -> let users override or retire memory
audit    -> inspect why memory changed
```

Mode comparison:

| Mode | Purpose | Typical output |
| --- | --- | --- |
| Observe | Extract candidate memory from dialogue or structured payloads. | Candidate `MemoryItem` list |
| Write | Decide whether memory should persist. | `WriteDecision` and audit events |
| Retrieve | Select memory for the current query. | Relevant active memory subset |
| Adapt | Convert memory signals into answer behavior. | `ResponsePolicy` |
| Correct | Apply explicit user correction or retirement. | Updated active memory and audit events |
| Audit | Explain lifecycle changes. | Write, merge, reject, retire, and correct logs |

---

## Correction And Audit

Users can explicitly correct or retire memory. Corrections are treated as
high-authority writes and create audit events.

Audit actions:

- `write`: new memory persisted
- `merge`: duplicate or equivalent memory merged
- `reject`: candidate failed write policy
- `retire`: previous memory made inactive
- `correct`: user correction inserted

This makes the memory system explainable. A caller can inspect not only what is
remembered, but why it was remembered and what it replaced.

---

## Structured LLM Extraction

The rule extractor is intentionally small. Production systems should use an LLM
to produce structured candidate memories, then pass them through the same write
policy and store.

Expected shape:

```json
{
  "memories": [
    {
      "type": "preference",
      "key": "response_opening",
      "value": "answer_first",
      "confidence": 0.9,
      "evidence": "先给结论",
      "exclusive_group": "response_opening",
      "coexistence_rule": "mutually_exclusive",
      "dynamics": "not_applicable",
      "tags": []
    }
  ]
}
```

`StructuredMemoryParser` converts this payload into `MemoryItem` objects. The
same write policy, audit, persistence, and retrieval layers then apply.

---

## Spec Gap

The initial spec calls for a new memory system from the user's perspective:
what to remember, how to remember it, and how to use it to make answers more
personally adaptive. The current implementation covers the skeleton but still
has important gaps.

| Spec area | Current state | Gap to close |
| --- | --- | --- |
| Events | Basic event memory exists. | Need richer event ontology, causal links, follow-up tasks, and event-to-state transitions. |
| Static / dynamic states | `static`, `semi_static`, `fluid`, and registry defaults exist. | Need richer TTL policies, transition rules, and state history summarization. |
| Mutual exclusion | Implemented through `exclusive_group` and `MemorySlotRegistry`. | Need configurable project/user-level registry loading instead of only built-in defaults. |
| Interests | Long-term and short-term interest slots exist. | Need recency scoring, frequency tracking, and interest decay. |
| Profile | Basic inferred profile dimensions exist. | Need psychology-backed trait model, confidence aggregation, evidence accumulation, and user-visible explanations. |
| Response adaptation | `ResponsePolicy` controls tone, detail, structure, decision mode, pace, empathy, and follow-up. | Need policy-to-answer generation, evaluation, and per-domain policy tuning. |
| LLM extraction | Structured parser exists. | Need live LLM extractor, JSON schema validation, retries, and contradiction checks. |
| Retrieval | Keyword/rule retrieval exists. | Need semantic retrieval, query intent classification, and policy-aware ranking. |
| Correction | Explicit correction and retirement exist. | Need UX for reviewing memory and accepting/rejecting suggestions. |
| Audit | Memory lifecycle audit exists. | Need diff UI, export, and privacy review. |
| Persistence | Local JSON and SQLite session repositories exist. | Need migrations, encryption, backups, and multi-user auth. |

---

## API

Start the service:

```bash
uvicorn app:app --reload
```

Storage backend defaults to local JSON files. Use SQLite when you want a single
local database file:

```bash
AME_STORAGE_BACKEND=sqlite uvicorn app:app --reload
```

Optional storage path overrides:

```bash
AME_DATA_DIR=/var/lib/adaptive-memory
AME_JSON_SESSION_DIR=/var/lib/adaptive-memory/sessions
AME_SQLITE_DB_PATH=/var/lib/adaptive-memory/adaptive_memory.sqlite3
```

Health check:

```bash
curl http://127.0.0.1:8000/health
```

Inspect supported memory slots:

```bash
curl http://127.0.0.1:8000/memory-slots
```

Ingest a raw dialogue turn:

```bash
curl -X POST http://127.0.0.1:8000/sessions/demo/ingest \
  -H 'Content-Type: application/json' \
  -d '{"text":"我29岁，硕士毕业，现在单身，最近在找工作。"}'
```

Ingest structured LLM extraction output:

```bash
curl -X POST http://127.0.0.1:8000/sessions/demo/ingest-structured \
  -H 'Content-Type: application/json' \
  -d '{"payload":{"memories":[{"type":"preference","key":"response_opening","value":"answer_first","confidence":0.9,"evidence":"先给结论","exclusive_group":"response_opening"}]}}'
```

Retrieve relevant memory and response policy:

```bash
curl -X POST http://127.0.0.1:8000/sessions/demo/query \
  -H 'Content-Type: application/json' \
  -d '{"query":"给我一点求职建议，回答直接一点。"}'
```

Build model-ready prompt context:

```bash
curl -X POST http://127.0.0.1:8000/sessions/demo/prompt-context \
  -H 'Content-Type: application/json' \
  -d '{"query":"给我一点求职建议，回答直接一点。"}'
```

Inspect active memories:

```bash
curl http://127.0.0.1:8000/sessions/demo/memories
```

Correct a memory:

```bash
curl -X POST http://127.0.0.1:8000/sessions/demo/memories/correct \
  -H 'Content-Type: application/json' \
  -d '{"memory_type":"state","key":"relationship_status","value":"dating","evidence":"我刚才说错了，现在是恋爱中","dynamics":"semi_static"}'
```

Retire a memory:

```bash
curl -X POST http://127.0.0.1:8000/sessions/demo/memories/retire \
  -H 'Content-Type: application/json' \
  -d '{"key":"current_emotional_state","memory_type":"state","reason":"no longer current"}'
```

Read audit events:

```bash
curl http://127.0.0.1:8000/sessions/demo/audit
```

Reset a session:

```bash
curl -X POST http://127.0.0.1:8000/sessions/demo/reset
```

---

## Local Development

Install dependencies:

```bash
python3 -m pip install -r requirements.txt
```

Run the demo:

```bash
python3 demo.py
```

Run with custom turns:

```bash
python3 demo.py \
  --turn "我29岁，硕士毕业，现在单身。" \
  --turn "最近找工作很焦虑，回答直接一点，先给结论。"
```

Run tests:

```bash
python3 -m unittest discover -s tests -p 'test_*.py'
```

Session files are stored under:

```bash
data/sessions/<session_id>.json
```

SQLite mode stores data under:

```bash
data/adaptive_memory.sqlite3
```

Runtime session JSON and SQLite files are ignored by git.

---

## Example Prompt Context

`/prompt-context` returns a model-facing object with:

- `system_prompt`
- `relevant_memory_lines`
- `response_policy`
- `assembled_prompt`

The assembled prompt is intentionally explicit:

```text
[System Guidance]
Use the response policy as the main control layer.

[Relevant User Memory]
- work_status: job_seeking
- response_opening: answer_first

[Response Policy]
- tone=direct_but_warm
- structure=answer_first
- decision_mode=give_recommendation

[Current User Query]
给我一点求职建议
```

---

## Current Limitations

- The built-in raw dialogue extractor is rule-based and Chinese-first.
- Retrieval is keyword and rule weighted, not embedding based.
- Persistence is local JSON or SQLite; production migrations, encryption, backups, and auth are still missing.
- Profile inference is deterministic and narrow.
- There is no production LLM call in this repository yet.
- There is no authentication layer around the FastAPI service.
- There is no UI for memory review, correction, or audit inspection.

These are deliberate prototype boundaries. The architecture keeps extraction,
write policy, storage, retrieval, and prompt assembly separate so each layer can
be upgraded independently.

---

## Roadmap

1. Add a declarative memory slot registry and state-machine configuration.
2. Connect `StructuredMemoryParser` to a production LLM extraction call.
3. Add semantic retrieval with embeddings.
4. Add configurable decay policies by memory type and dynamics.
5. Add contradiction detection beyond exclusive groups.
6. Add a memory review UI for accepting, correcting, and retiring memories.
7. Add production-grade migrations and encrypted persistence.
8. Add policy-conditioned answer generation over `assembled_prompt`.
9. Add privacy controls for sensitive memory categories.
10. Add offline evaluation for personalization quality.

---

## Star History

![Star History](https://api.star-history.com/svg?repos=2sao7sao/adaptive-memory-engine&type=Date)

---

## Commit Activity

![Commit Activity Graph](https://github-readme-activity-graph.vercel.app/graph?username=2sao7sao&repo=adaptive-memory-engine&theme=github-compact)

---

## Repository Status

This project is an early prototype. It is useful for design exploration,
integration experiments, and validating the architecture of a personalized
memory system. It is not yet a production-grade memory service.

## License

MIT License. See [LICENSE](LICENSE).
