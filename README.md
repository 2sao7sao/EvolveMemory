<img src="assets/adaptive-memory-engine-hero.png" alt="EvolveMemory banner" width="100%" />

<p align="center">
  <a href="./README.zh-CN.md">简体中文</a>
  ·
  <a href="https://2sao7sao.github.io/EvolveMemory/">Product Page</a>
  ·
  <a href="./examples/adaptive_memory_replay.md">Adaptive Replay</a>
  ·
  <a href="./CONTRIBUTING.md">Contributing</a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.11%2B-2563eb" alt="Python 3.11+">
  <img src="https://github.com/2sao7sao/EvolveMemory/actions/workflows/ci.yml/badge.svg" alt="CI status">
  <img src="https://img.shields.io/badge/evals-deterministic-167b63" alt="Deterministic evals">
  <img src="https://img.shields.io/badge/license-MIT-blue" alt="MIT license">
</p>

# EvolveMemory

**Adaptive memory runtime: decide what to remember, what to use, what to hide, and what to forget.**

Memory should make an AI feel more useful and natural. It should not make the
assistant sound like it is dragging old private details into every answer.

EvolveMemory treats memory as a product control layer:

> Remember selectively. Retrieve candidates. Gate permission. Compile safe prompt context. Correct or forget on demand.

## Core Thesis

Retrieval is not permission. A retrieved memory is only a candidate signal until the memory-use gate decides whether it may shape direct facts, style, follow-up, hidden constraints, clarification, summarize-only context, or suppression. LLM extraction follows the same rule: model output can propose candidates, but deterministic validation and write governance remain the writer of record.

![EvolveMemory adaptive replay](docs/assets/evolvememory-gate-replay.svg)

## 30-Second Product Path

```text
User turn
  -> memory proposal
  -> write governance
  -> normalized store
  -> retrieval planning
  -> memory-use gate
  -> response policy
  -> safe prompt context
  -> correction / audit
```

| Common memory system | EvolveMemory |
| --- | --- |
| Saves every extracted fact | Scores whether a candidate should be written |
| Retrieves and injects memories | Separates retrieval from permission |
| Mentions personal details too eagerly | Uses direct, style-only, follow-up, summarize-only, hidden, clarify, or suppress actions |
| Makes prompts longer | Compiles only prompt-safe context |
| Forgets poorly | Supports correction, retirement, forget-all, review queue, and audit export |

## 5-Minute Replay

```bash
git clone https://github.com/2sao7sao/EvolveMemory.git
cd EvolveMemory
python -m pip install -r requirements.txt
python -m memory_system.demo
```

Expected shape:

```text
# EvolveMemory Adaptive Replay

status: PASS
active_memories_before_correction: 7
accepted_candidates: 4/4
gate_eval: 8/8

## Product metrics
- gate_action_accuracy: 1.00 (8/8)
- explicit_suppression_rate: 1.00 (1/1)
- style_continuity_rate: 1.00 (4/4)
- prompt_safety_rate: 1.00 (1/1)
- correction_retirement_rate: 1.00 (2/2)
```

`python examples/replay_adaptive_memory.py` runs the same product path.

## What The Replay Proves

The replay stores two turns:

| Turn | Meaning |
| --- | --- |
| `我最近准备面试，有点焦虑。` | Ongoing event + sensitive emotional state |
| `回答直接一点，先给结论。` | Durable communication preference |

Then it asks two different queries:

| Query | Correct memory behavior |
| --- | --- |
| `面试怎么准备？` | Use interview event as `follow_up`; apply style preferences without exposing raw profile facts. |
| `今天只帮我 review Python 代码，不用提面试。` | Suppress the interview event; keep style adaptation; avoid direct visible memory injection. |

Finally it simulates a correction: the user does not want anxiety remembered.
The product path retires both the sensitive state and its derived profile signal.

## Metrics That Map To Code

| Metric | What it measures | Runtime source |
| --- | --- | --- |
| `gate_action_accuracy` | Expected memory-use actions across regression cases | `evals.runner.run_gate_eval` |
| `explicit_suppression_rate` | Whether explicit "do not mention X" suppresses the matching event | `MemoryUseGate` |
| `style_continuity_rate` | Whether style preferences remain useful across relevant and unrelated queries | `SessionMemoryRuntime.query` |
| `prompt_safety_rate` | Whether no direct visible memory is injected for the no-mention query | `PromptContextBuilder` |
| `correction_retirement_rate` | Whether correction retires sensitive state and derived profile memory | `SessionMemoryRuntime.retire_memory` |
| `extraction` | Whether provider-free LLM payloads validate, normalize, or reject correctly | `LLMMemoryProposalExtractor` |
| `write_decision` | Whether deterministic write governance creates, reviews, supersedes, or evidence-merges | `MemoryOperationPlanner` |
| `privacy_actions` | Whether retrieval/gating suppresses sensitive or non-promptable memories | `MemoryUseGate` |
| `v2_ingest` | Whether `/v2/users/{user_id}/turns/ingest` routes LLM payloads through governance | FastAPI v2 ingest |

Run deterministic evals:

```bash
python -m evals.runner --suite gate_eval
python -m evals.runner --suite product_replay_eval
python -m evals.runner --suite profile_evidence_eval
python -m evals.runner --suite response_policy_eval
python -m evals.runner --suite event_skill_eval
python -m evals.runner --suite prompt_context_safety_eval
python -m evals.runner --suite extraction_eval
python -m evals.runner --suite write_decision_eval
python -m evals.runner --suite retrieval_privacy_eval
python -m evals.runner --suite v2_ingest_eval
python -m evals.runner --suite all
```

## Developer Surface

```bash
# Run the product replay
python -m memory_system.demo

# Run the original extraction demo
python demo.py

# Start the API
uvicorn app:app --reload

# Use SQLite persistence
AME_STORAGE_BACKEND=sqlite uvicorn app:app --reload
```

Minimal runtime integration:

```python
from datetime import datetime
from zoneinfo import ZoneInfo

from memory_system import SessionMemoryRuntime

runtime = SessionMemoryRuntime(session_id="user-1")
now = datetime(2026, 5, 1, 9, 0, tzinfo=ZoneInfo("Asia/Shanghai"))

runtime.ingest_turn("回答直接一点，先给结论。", "turn_1", now)
context = runtime.prompt_context("帮我 review 这段代码。", now)
print(context["assembled_prompt"])
```

## Phase 2 Upgrade Highlights

This release deepens EvolveMemory from a governed memory store into a richer mental-model runtime:

| Upgrade | What changed | Runtime / eval |
| --- | --- | --- |
| Provider-free LLM proposal ingest | `/v2/users/{user_id}/turns/ingest` accepts `extractor="llm_payload"`; payloads become candidates only. | `app.py`, `LLMMemoryProposalExtractor`, `v2_ingest_eval` |
| Semantic proposal validation | LLM payloads normalize blank values, upgrade sensitive keys, reject third-party confusion, validate tags, and preserve `valid_to`. | `LLMProposalSchemaValidator`, `extraction_eval` |
| Evidence-accumulated mental models | Profiles now cover planning orientation, learning style, cognitive load, collaboration style, uncertainty tolerance, and risk posture. | `ProfileEvidenceExtractor`, `profile_evidence_eval` |
| Procedural collaboration memory | Explicit instructions such as checklist planning, example-first explanations, coaching style, and candid critique become policy-safe guidance. | `ResponsePolicyEngine`, `response_policy_eval` |
| Expanded response policy compiler | Memory can now shape reasoning depth, example density, initiative, challenge level, personalization strength, and follow-up budget. | `PromptContextBuilder`, `prompt_context_safety_eval` |
| Broader event state machines | Project and relationship event skills join career, learning, and life events with stricter privacy-aware follow-up rules. | `EventSkillRegistry`, `event_skill_eval` |
| Privacy and write evals | Deterministic suites cover extraction, write decisions, retrieval privacy, and v2 ingest. | `write_decision_eval`, `retrieval_privacy_eval` |

## Provider-Free LLM Proposal Ingest

The runtime can now accept model-produced proposal payloads without requiring a provider or network call. The LLM boundary is deliberately not a writer: the payload is parsed into candidate `MemoryRecord`s, then deterministic write governance decides create, merge, review, reject, or evidence-only update.

```json
{
  "session_id": "demo-session",
  "role": "user",
  "text": "回答直接一点。",
  "options": {
    "extractor": "llm_payload",
    "llm_payload": {
      "candidate_memories": [
        {
          "layer": "preference",
          "key": "communication_style",
          "value": "direct",
          "confidence": 0.9,
          "authority": "user_explicit",
          "sensitivity": "personal",
          "evidence": "回答直接一点"
        }
      ]
    }
  }
}
```

Invalid payloads return HTTP 422, and sensitive or restricted candidates still enter the review queue when policy requires confirmation.

## API Shape

| Endpoint | Purpose |
| --- | --- |
| `POST /v2/users/{user_id}/turns/ingest` | Ingest a user turn into the normalized runtime. |
| `POST /v2/users/{user_id}/memory/query` | Retrieve and gate memories for the current query. |
| `POST /v2/users/{user_id}/prompt-context` | Compile model-ready memory context. |
| `GET /v2/users/{user_id}/memory/review-queue` | Inspect memories requiring confirmation. |
| `POST /v2/users/{user_id}/memory/{memory_id}/correct` | Correct and retire conflicting records. |
| `POST /v2/users/{user_id}/memory/forget-all` | Clear memory with audit trail. |
| `GET /v2/users/{user_id}/memory/audit/export` | Export records, settings, events, and audit data. |

## Architecture

```mermaid
flowchart LR
  subgraph Observe["Observe and propose"]
    A["User turn"] --> B["Turn preprocessor"]
    B --> C["Rule / LLM proposal boundary"]
    C --> D["Schema validation and normalization"]
  end

  subgraph Govern["Write governance"]
    D --> E["Sensitivity and contradiction checks"]
    E --> F["Weighted write evaluator"]
    F --> G{"Create, merge, review, reject?"}
  end

  subgraph Store["Normalized memory runtime"]
    G --> H["Memory records"]
    G --> I["Review queue"]
    H --> J["Profile evidence ledger"]
    H --> K["Event state store"]
    H --> L["Audit log"]
  end

  subgraph Use["Use safely"]
    M["Current query"] --> N["Intent-aware retrieval planner"]
    H --> O["Hybrid scorer"]
    J --> P["Mental-model compiler"]
    K --> Q["Event follow-up policy"]
    N --> O
    O --> R["Memory-use gate"]
    P --> R
    Q --> R
    R --> S["Response policy"]
    S --> T["Safe prompt context"]
  end

  subgraph Improve["Govern and improve"]
    U["Correct / delete / forget-all"] --> H
    L --> V["Audit export"]
    T --> W["Profile / policy / event / safety evals"]
  end
```

## Stable vs Prototype

| Layer | Current status |
| --- | --- |
| Rule extraction, write policy, use gate, prompt context | Supported local product path |
| FastAPI endpoints and in-memory / SQLite persistence | Supported for prototypes |
| Review queue, correction, delete, forget-all, audit export | Implemented for governance demos |
| LLM proposal ingest | Provider-free payload parsing is wired into v2 ingest; provider-backed extraction is still prototype |
| Benchmarks | Deterministic regression/eval seeds only, not broad personal-memory benchmark claims |

## Fit / Non-Fit

Good fit:

| Product | Why |
| --- | --- |
| Personal assistants | Need durable style, events, and correction paths |
| AI companions | Need adaptation without creepy recall |
| Workflow agents | Need memory governance, audit, and prompt-safe context |
| Long-running sessions | Need stale-memory suppression and forget controls |

Poor fit:

| Product | Better choice |
| --- | --- |
| Stateless bots | Do not add memory when output should never adapt |
| Transcript search | Use search or RAG |
| Uninspectable black-box memory | Use a governed store first |
| Highly regulated production memory | Add policy review, privacy review, and red-team tests before launch |

## Repository Map

```text
memory_system/   runtime, demo report, extraction, gates, retrieval, context, storage
evals/           deterministic extraction, write, retrieval, ingest, gate, and replay evals
tests/           runtime, API, persistence, correction, prompt-safety tests
examples/        runnable replay and product walkthrough
docs/            GitHub Pages product page and design notes
app.py           FastAPI service
demo.py          local extraction demo
```

## Roadmap

| Area | Next step |
| --- | --- |
| Evaluation | Add noisy multi-turn, stale memory, answer-quality, and privacy stress suites |
| Extraction | Add provider-backed extraction and disagreement checks on top of the wired payload boundary |
| Privacy | Add sensitive-memory red-team prompts, encryption, and retention policy fixtures |
| Integration | Add chatbot, workflow, and multi-agent harness examples |

## Security

Do not commit real user transcripts, local SQLite stores, session JSON, API keys,
or debug exports containing personal data. See [SECURITY.md](SECURITY.md).

## License

MIT. See [LICENSE](LICENSE).
