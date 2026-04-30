# Adaptive Memory Engine

Adaptive Memory Engine is a prototype memory system for conversational AI.
Its goal is not to build a bigger transcript store. Its goal is to turn user
dialogue into structured memory, decide what is worth keeping, and convert
active memory into response guidance that makes the model answer in a way that
fits the user.

The core question is:

```text
Given what we know about this user, how should the model respond right now?
```

## Why This Exists

Most memory systems stop at storage and retrieval. That is not enough for a
personal assistant. Useful memory has to influence behavior:

- what the model remembers
- how long the memory remains valid
- whether memories conflict or coexist
- how a user can correct memory
- which memories matter for the current query
- how retrieved memory changes tone, structure, detail, empathy, and follow-up behavior

This repository implements that end-to-end loop in a small, inspectable Python
service.

## System Flow

```text
dialogue turn
  -> candidate memory extraction
  -> write policy scoring
  -> memory store update
  -> profile inference
  -> query-aware retrieval
  -> response policy generation
  -> model-ready prompt context
```

Memory is not pushed directly into the answer prompt. Relevant memories are
first converted into a response policy such as:

```json
{
  "tone": "direct_but_warm",
  "detail_level": "low",
  "structure": "answer_first_then_steps",
  "decision_mode": "give_recommendation",
  "pace": "medium",
  "empathy_level": "high",
  "followup_style": "clarify_when_needed"
}
```

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

Some states are mutually exclusive. Some can coexist. For example,
`relationship_status=single` and `relationship_status=dating` should not both
be active, while `interest_long_term=skiing` and `interest_short_term=fishing`
can coexist.

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
rigid label or personality type. It is a set of revisable dimensions with
confidence and evidence.

Current profile dimensions include:

- `structure_preference_level`
- `directness_preference_level`
- `detail_tolerance`
- `emotional_support_need`
- `pace_preference`

## Components

| Component | File | Responsibility |
| --- | --- | --- |
| `MemoryItem` | `memory_system/schema.py` | Normalized memory record with confidence, validity, coexistence, and source metadata. |
| `ResponsePolicy` | `memory_system/schema.py` | Compact answer-control object used by the model-facing layer. |
| `MemoryAuditEvent` | `memory_system/schema.py` | Explains memory writes, merges, rejections, retirements, and corrections. |
| `DialogueMemoryExtractor` | `memory_system/engine.py` | Rule-based Chinese dialogue extractor for the current prototype. |
| `MemoryWriteEvaluator` | `memory_system/engine.py` | Scores candidate memories before persistence. |
| `MemoryStore` | `memory_system/engine.py` | Applies active-memory, merge, retirement, correction, and audit rules. |
| `ProfileInferencer` | `memory_system/engine.py` | Infers user profile dimensions from active states and preferences. |
| `QueryMemoryRetriever` | `memory_system/engine.py` | Retrieves memories relevant to the current user query. |
| `ResponsePolicyEngine` | `memory_system/engine.py` | Converts memory signals into response policy. |
| `StructuredMemoryParser` | `memory_system/structured.py` | Parses LLM-produced JSON extraction payloads into `MemoryItem` objects. |
| `PromptContextBuilder` | `memory_system/prompting.py` | Builds model-ready prompt context from relevant memory and policy. |
| `DiskSessionRepository` | `memory_system/persistence.py` | Persists session memory and audit events to local JSON files. |
| `SessionMemoryRuntime` | `memory_system/service.py` | Orchestrates extraction, scoring, storage, inference, retrieval, and prompt context. |
| FastAPI app | `app.py` | Provides HTTP endpoints for integration. |
| Demo CLI | `demo.py` | Runs the memory loop locally with sample turns. |

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

## State Machine Rules

The store uses active-time windows rather than deleting history.

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

## API

Start the service:

```bash
uvicorn app:app --reload
```

Health check:

```bash
curl http://127.0.0.1:8000/health
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

Runtime session JSON is ignored by git.

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

## Current Limitations

- The built-in raw dialogue extractor is rule-based and Chinese-first.
- Retrieval is keyword and rule weighted, not embedding based.
- Persistence is local JSON, not a database.
- Profile inference is deterministic and narrow.
- There is no production LLM call in this repository yet.
- There is no authentication layer around the FastAPI service.

These are deliberate prototype boundaries. The architecture keeps extraction,
write policy, storage, retrieval, and prompt assembly separate so each layer can
be upgraded independently.

## Roadmap

- Connect `StructuredMemoryParser` to a production LLM extraction call.
- Add semantic retrieval with embeddings.
- Add configurable decay policies by memory type and dynamics.
- Add contradiction detection beyond exclusive groups.
- Add a memory review UI for accepting, correcting, and retiring memories.
- Add database-backed repositories.
- Add policy-conditioned answer generation over `assembled_prompt`.
- Add privacy controls for sensitive memory categories.

## Repository Status

This project is an early prototype. It is useful for design exploration,
integration experiments, and validating the architecture of a personalized
memory system. It is not yet a production-grade memory service.

## License

MIT License. See [LICENSE](LICENSE).
