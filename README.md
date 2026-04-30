# New Memory System

## Goal

This project prototypes a user-centric memory system for conversational AI.
The system does not treat memory as a raw transcript archive. It turns dialogue
into structured memory and then converts memory into a response policy that
helps the model answer in a way that better fits the user.

The design centers on three questions:

1. What should be remembered
2. How should it be remembered
3. How should memory change the answer

## Core Principle

The key output of the system is not a user profile document. It is a dynamic
answering strategy:

- What tone should be used
- How much detail should be given
- Whether the answer should be conclusion-first or process-first
- Whether the model should recommend, explore, or ask clarifying questions
- How much empathy or efficiency should be injected

## Memory Layers

### 1. Events

Discrete things that happened to the user and can influence future context.

Examples:

- changed jobs
- broke up
- moved cities
- started preparing for an exam
- recently began learning skiing

Design notes:

- event memories are time-sensitive
- event memories can create or update states
- event memories are often the trigger for follow-up support

### 2. States

Facts or conditions describing what the user is like now.

States are split into three engineering layers:

- static: stable, low-frequency change
- semi-static: changes occasionally
- fluid: phase-based or short-lived

Examples:

- static: age band, education level
- semi-static: relationship status, work status, city
- fluid: busy this week, anxious recently, preparing for interviews

State design rules:

- some states are mutually exclusive
- some states can coexist
- fluid states should usually have a shorter lifetime

### 3. Preferences

How the user prefers to be served.

Examples:

- prefers direct communication
- wants step-by-step guidance
- likes answer first
- dislikes verbose explanations
- wants strong recommendations instead of neutral framing

This layer is the most important short path from memory to answer quality.

### 4. Profile

Profile is not a rigid label. It is a set of inferred dimensions with
confidence scores and explicit evidence.

Recommended dimensions:

- structure_preference
- directness_preference
- control_need
- detail_preference
- emotional_support_need
- exploration_preference

Profile should remain revisable. It is an inference layer, not a verdict.

## Data Model

Each memory item uses a normalized schema:

```json
{
  "id": "mem_001",
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
  "coexistence_rule": "mutually_exclusive"
}
```

Required fields:

- `type`: `event`, `state`, `preference`, `profile`
- `key`: normalized semantic slot
- `value`: normalized slot value
- `confidence`: confidence in `[0, 1]`
- `source`: where the memory came from
- `evidence`: the text snippet or reason

Recommended control fields:

- `valid_from`
- `valid_to`
- `confirmed_by_user`
- `exclusive_group`
- `coexistence_rule`

## State Machine Design

Use state machines only for the slots that truly need them.

### Mutually exclusive states

Examples:

- `relationship_status`: single, dating, married
- `education_level`: associate, bachelor, master, phd
- `communication_pace`: slow, medium, fast

When a new active value enters the same exclusive group, the old value should
be retired instead of deleted.

### Coexisting states

Examples:

- `interests`: fishing, skiing, photography
- `skills_in_progress`: interview_prep, english_learning
- `response_opening` and `explanation_structure`: `answer_first` can coexist with `step_by_step`

These should be stored as parallel memories rather than a single slot.

### Lifetime rules

- static states usually persist until contradicted
- semi-static states persist until replaced
- fluid states should have shorter validity windows or decay faster
- profile dimensions should be recalculated when strong new evidence appears

## Write Policy

Not everything should enter long-term memory.

A simple write heuristic:

`memory_value = stability x reuse x personalization_gain x confidence`

Only persist memories that are likely to matter later.

High-value candidates:

- stable user facts
- repeated preferences
- major life events
- ongoing work or emotional context that shapes current answers

Low-value candidates:

- one-off throwaway remarks
- unstable guesses with weak evidence
- details that do not affect future responses

## Retrieval and Usage

The system should not dump all memory back into the prompt.

Instead:

1. retrieve only relevant memory for the current query
2. aggregate signals into a response policy
3. answer using the policy, not the raw memory list

Example response policy:

```json
{
  "tone": "direct_but_warm",
  "detail_level": "medium",
  "structure": "answer_first",
  "decision_mode": "give_recommendation",
  "pace": "fast",
  "empathy_level": "moderate",
  "followup_style": "only_when_blocked"
}
```

## Architecture

The prototype is intentionally small and splits the system into four modules:

1. `DialogueMemoryExtractor`
   Converts raw dialogue into candidate memories.

2. `MemoryStore`
   Applies coexistence and exclusivity rules and keeps active memory.

3. `ProfileInferencer`
   Infers continuous user traits from accumulated evidence.

4. `ResponsePolicyEngine`
   Converts active memory into a response policy used by the model.

5. `QueryMemoryRetriever`
   Selects the subset of active memory that is relevant to the current query.

6. `SessionMemoryRuntime`
   Wraps ingest, inference, retrieval, and policy generation for one session.

7. `DiskSessionRepository`
   Persists session memories to disk so the system survives process restarts.

8. `PromptContextBuilder`
   Converts relevant memories and response policy into model-ready prompt context.

## Prototype Scope

This repository provides a local Python prototype that can:

- extract candidate event, state, and preference memories from Chinese dialogue
- manage mutually exclusive and coexisting memory slots
- infer profile dimensions from explicit preferences and recent states
- retrieve only query-relevant memory before answer generation
- generate a response policy
- persist session memory to local disk
- assemble a model-ready prompt context
- serve the pipeline over FastAPI for local integration

It is rule-based on purpose so the architecture can be inspected before a model
driven extractor is introduced.

## Run

Run the built-in demo:

```bash
python3 demo.py
```

Run with custom turns:

```bash
python3 demo.py --turn "我29岁，硕士毕业，现在单身。" --turn "最近找工作很焦虑，回答直接一点，先给结论。"
```

Run tests:

```bash
python3 -m unittest discover -s tests -p 'test_*.py'
```

Run the local API service:

```bash
uvicorn app:app --reload
```

Ingest a turn:

```bash
curl -X POST http://127.0.0.1:8000/sessions/demo/ingest \
  -H 'Content-Type: application/json' \
  -d '{"text":"我29岁，硕士毕业，现在单身，最近在找工作。"}'
```

Query with relevant-memory retrieval:

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

Session files are stored under:

```bash
data/sessions/<session_id>.json
```

## Next Steps

- add an LLM-backed extractor that outputs normalized memory candidates
- add retrieval filtering by user query intent
- add memory decay and contradiction handling
- add explicit user correction and memory audit logs
- add LLM-backed answer generation over prompt context
