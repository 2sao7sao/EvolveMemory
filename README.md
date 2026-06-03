<img src="assets/readme-banner.svg" alt="EvolveMemory banner" width="100%" />

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
  <img src="https://img.shields.io/badge/python-3.11%2B-ff5aa5" alt="Python 3.11+">
  <img src="https://github.com/2sao7sao/EvolveMemory/actions/workflows/ci.yml/badge.svg" alt="CI status">
  <img src="https://img.shields.io/badge/evals-deterministic-b8eee4" alt="Deterministic evals">
  <img src="https://img.shields.io/badge/license-MIT-ff5aa5" alt="MIT license">
</p>

# EvolveMemory

**A governed adaptive memory runtime for AI personalization.**

EvolveMemory is not a transcript store and not a vector database wrapper. It is
a runtime for deciding what should be remembered, what is only a candidate,
what may influence an answer, what must stay hidden, and what should be
corrected or forgotten.

> Retrieval is not permission. A retrieved memory is only a candidate until the
> memory-use gate decides whether it can be used directly, converted into style
> policy, used as a follow-up cue, kept as a hidden constraint, summarized, or
> suppressed.

## Runtime Contract

```text
user turn
  -> proposal extraction
  -> write governance
  -> normalized store
  -> retrieval plan
  -> hybrid math score
  -> memory-use gate
  -> response policy
  -> prompt-safe context
  -> correction / audit / evals
```

<img src="assets/runtime_contract_map_v2.svg" alt="EvolveMemory runtime modes: observe, write, retrieve, adapt, correct, audit" width="100%" />

| Runtime boundary | Contract |
| --- | --- |
| Observe | Extract candidates from a turn or provider-free LLM payload. |
| Govern | Validate, score, review, reject, merge, or supersede candidates. |
| Store | Keep normalized records, evidence, event states, settings, and audit logs. |
| Retrieve | Rank candidates by intent, relevance, lifecycle, causal impact, and semantic gravity. |
| Gate | Decide allowed use: direct, style-only, follow-up, clarify, hidden, summary, suppress. |
| Compile | Produce prompt-safe sections rather than raw private memory injection. |
| Correct | Retire, delete, forget-all, or export audit evidence. |

## What Ships In This Repo

| Surface | What it gives you |
| --- | --- |
| Memory runtime | Deterministic local engine for ingest, retrieval, gating, prompt context, correction, and audit. |
| FastAPI service | v2 endpoints for turn ingest, memory query, prompt context, review queue, correction, forget-all, and export. |
| Math model | Inspectable scoring objects for retrieval, activation, semantic gravity, causal relevance, and write decisions. |
| Governance | Write policy, sensitivity checks, review paths, correction retirement, and audit evidence. |
| Evals | Regression suites for extraction, write decisions, gate actions, privacy, prompt safety, and replay coherence. |
| Product docs | GitHub Pages, replay examples, diagrams, and design review notes. |

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

The replay stores two user turns:

| Turn | Memory meaning |
| --- | --- |
| `我最近准备面试，有点焦虑。` | Ongoing event plus sensitive emotional state. |
| `回答直接一点，先给结论。` | Durable communication and structure preference. |

Then it asks two different queries:

| Query | Correct behavior |
| --- | --- |
| `面试怎么准备？` | Use the interview event as `follow_up`; apply style policy without exposing raw profile facts. |
| `今天只帮我 review Python 代码，不用提面试。` | Suppress the interview event; keep style adaptation; avoid direct visible memory injection. |

Finally it simulates a correction: the user does not want anxiety remembered.
The runtime retires both the sensitive state and the derived profile signal.

<img src="docs/assets/replay_gate_summary_v2.svg" alt="Replay proof for gate, suppression, style continuity, and correction" width="100%" />

## Mathematical Runtime

EvolveMemory treats memory behavior as a scored, inspectable decision chain.
Rules are deterministic today, but each important module emits factors,
weights, formulas, rationale, and a version so it can later be calibrated or
learned from feedback.

`ScoreBreakdown` is the common explanation object:

```python
ScoreBreakdown(
    name="retrieval",
    score=0.81,
    factors={"keyword": 0.5, "activation": 0.72, "semantic_gravity": 0.88},
    weights={"keyword": 0.22, "activation": 0.14, "semantic_gravity": 0.06},
    probability=0.81,
    formula="S_ret-v3=...",
    rationale=["career query depends on current work or event state"],
    version="retrieval-v3.0",
)
```

Read the math runtime as one pipeline:

| Stage | Question answered | Output |
| --- | --- | --- |
| Retrieval score | Which candidate memories should be inspected first? | Ranked candidate list. |
| Activation | Is this memory still active at this moment? | Lifecycle-aware factor `A`. |
| Semantic gravity | Should weak-match but high-impact context remain visible? | Impact factor `G`. |
| Causal relevance | Would this memory change the safe or useful answer? | Dependency factor `C`. |
| Use gate | How may ranked memories affect the prompt? | direct, style, follow-up, hidden, summary, suppress. |
| Write governance | Can an LLM proposal become a formal memory? | create, review, merge, supersede, reject. |

### 1. Retrieval Score

Retrieval ranks candidates. It still does not grant permission.

```text
S_ret_v3 = clamp(
  0.22*K_keyword
+ 0.22*E_embedding
+ 0.14*F_freshness
+ 0.14*L_layer_prior
+ 0.14*A_activation
+ 0.08*C_causal_relevance
+ 0.06*G_semantic_gravity
)
```

All factors are normalized to `0..1`, and the weights sum to `1.00`. The
score answers one question only: **which candidates should be inspected
first?** The memory-use gate still decides visibility and allowed use.

| Symbol | Runtime factor | Meaning |
| --- | --- | --- |
| `K` | `keyword` | Lexical overlap with the current query. |
| `E` | `embedding` | Deterministic embedding-like similarity for local tests and demos. |
| `F` | `freshness` | Time freshness of the memory. |
| `L` | `layer_prior` | Whether the query intent wants this memory layer. |
| `A` | `activation` | Lifecycle-aware activation over confidence, age, recurrence, anomaly, fatigue. |
| `C` | `causal_relevance` | Whether the memory changes the safe or useful answer. |
| `G` | `semantic_gravity` | Human-context importance even when wording does not match. |

Retrieval-v3 is intentionally hybrid:

| Layer | Why it exists |
| --- | --- |
| Match | `keyword` and `embedding` keep ordinary relevance strong. |
| Lifecycle | `freshness`, `layer_prior`, and `activation` stop stale or wrong-layer memories from dominating. |
| Impact | `causal_relevance` and `semantic_gravity` recover memories that matter even when wording is weak. |

### 2. Activation And Temporal Anomaly

Some memories can be stored but should not currently affect behavior. Activation
models lifecycle decay, reinforcement, temporal anomaly, and fatigue.

```text
log_A = base_prior[lifecycle]
      + log(confidence)
      - decay_per_day[lifecycle] * age_days
      + reinforcement_weight * log(1 + recurrence_count)
      + anomaly_weight * temporal_anomaly
      - fatigue_weight * fatigue

A_activation = sigmoid(log_A)
```

The anomaly input is derived before activation:

```text
temporal_anomaly =
  0.50 * duration_ratio
+ 0.30 * recurrence_factor
+ 0.20 * severity_prior
```

This separates ordinary recency from persistent state risk: a normal preference
can quietly remain long term, while a recurring volatile state can stay visible
for careful follow-up or review.

<img src="assets/activation_model_v2.svg" alt="State temporal anomaly model with TTL, recurrence, anomaly score, and phase transitions" width="100%" />

### 3. Semantic Gravity

Semantic gravity prevents important life or safety context from being lost just
because lexical overlap is weak. Job loss, interviews, exams, health
constraints, relationship transitions, and persistent emotional state can
matter more than a generic preference.

```text
G_social = clamp(
  base_gravity[key_or_value]
* cultural_context_weight
* life_stage_modifier
)

G_final = clamp(
  G_social
* (1 + 0.35 * personal_importance)
/ (1 + 0.50 * fatigue)
)
```

Semantic gravity is not permission either. It only prevents high-impact context
from disappearing before the use gate can decide whether it should be mentioned,
hidden, summarized, or suppressed.

<img src="assets/semantic_gravity_model_v2.svg" alt="Semantic gravity model with context resolution, social gravity, and individual modulation" width="100%" />

### 4. Causal Relevance

Causal retrieval asks: would this memory change the safe or useful answer?

```text
C(m, q) = rule_risk_or_dependency(m, q)
```

The current implementation is not a black-box causal model. It is an auditable
dependency rule set: health or medication constraints score `1.00` for alcohol
queries, career events score about `0.90` for job-search queries, and exam,
relationship, and style queries step down through their own dependency rules.
The goal is to lift answer-changing memories into the candidate set before the
gate decides visibility.

Example: if the user asks whether they can drink at a party, a medication or
allergy memory should surface even when it is not the highest keyword match.
That memory is still only a retrieved candidate; the use gate decides whether
and how it can affect the answer.

## Write Governance And Inference Validation

LLM output is never the writer of record. A model can propose memories, but
validation and deterministic write governance decide whether each candidate is
created, rejected, reviewed, superseded, or merged as evidence.

<img src="assets/write_governance_model_v2.svg" alt="Write governance model with proposal boundary, weighted score, hard policy, and decision paths" width="100%" />

Write governance uses a weighted score:

```text
S_write = clamp(
  0.18*C_confidence
+ 0.16*R_future_reuse
+ 0.14*P_personalization_gain
+ 0.12*T_temporal_stability
+ 0.10*A_user_authority
+ 0.10*E_evidence_quality
+ 0.08*N_novelty
+ 0.07*U_actionability
+ 0.05*V_privacy_adjustment
)
```

`S_write` is only the weighted part of the decision. Hard policy checks still
override it: disabled settings reject, explicit do-not-remember rejects,
restricted memories require consent, low-confidence sensitive memories require
review, and contradictions may merge, supersede, or ask the user.

| Symbol | Factor |
| --- | --- |
| `C` | Candidate confidence. |
| `R` | Future reuse value. |
| `P` | Personalization gain. |
| `T` | Temporal stability. |
| `A` | User/source authority. |
| `E` | Evidence quality. |
| `N` | Novelty against existing memory. |
| `U` | Actionability. |
| `V` | Privacy adjustment. |

| Result path | Decision owner |
| --- | --- |
| `create` | Score passes threshold and no review policy blocks it. |
| `review` | Sensitivity, restricted consent, low confidence, or lower authority needs user confirmation. |
| `merge` | Duplicate evidence should attach to an existing record. |
| `supersede` | A higher-or-equal authority candidate replaces an exclusive conflicting value. |
| `reject` | Settings, explicit refusal, hard confidence floor, or low weighted utility blocks the write. |

## Memory-Use Gate And Prompt Safety

The gate turns ranked candidates into allowed actions.

```text
S_gate = clamp(
  0.22*query_relevance
+ 0.14*freshness
+ 0.14*authority
+ 0.16*utility
+ 0.14*privacy_safety
+ 0.08*user_preference_alignment
+ 0.06*token_efficiency
+ 0.06*contradiction_safety
)
```

The gate is not another retrieval score. It separates usefulness from
visibility: a high-scoring memory may still become `style_only`,
`summarize_only`, or `suppress` because of privacy, allowed-use constraints,
explicit suppression, or sensitive-memory policy.

| Gate action | Prompt channel |
| --- | --- |
| `use_directly` | Direct user facts, only when safe to mention. |
| `style_only` | Style policy without exposing raw private evidence. |
| `follow_up` | At most one short progress cue. |
| `hidden_constraint` | Internal policy constraint, not visible to the user. |
| `clarify` | Ask for current truth before using uncertain memory. |
| `summarize_only` | Aggregate context only, no details. |
| `suppress` | Audit only; not used in the prompt. |

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

## API Surface

| Endpoint | Purpose |
| --- | --- |
| `POST /v2/users/{user_id}/turns/ingest` | Ingest a user turn or provider-free LLM proposal payload. |
| `POST /v2/users/{user_id}/memory/query` | Retrieve, score, and gate memories for the current query. |
| `POST /v2/users/{user_id}/prompt-context` | Compile model-ready memory context. |
| `GET /v2/users/{user_id}/memory/review-queue` | Inspect memories requiring confirmation. |
| `POST /v2/users/{user_id}/memory/{memory_id}/correct` | Correct and retire conflicting records. |
| `POST /v2/users/{user_id}/memory/forget-all` | Clear memory with audit trail. |
| `GET /v2/users/{user_id}/memory/audit/export` | Export records, settings, events, and audit data. |

## Evaluation

Run deterministic evals:

```bash
python -m evals.runner --suite retrieval_math_eval
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

| Eval | Contract covered |
| --- | --- |
| `retrieval_math_eval` | Activation, causal relevance, and semantic gravity affect ranking. |
| `gate_eval` | Expected memory-use actions match regression cases. |
| `prompt_context_safety_eval` | Profile and sensitive memory stay out of direct prompt facts. |
| `write_decision_eval` | Governance creates, rejects, reviews, supersedes, or evidence-merges correctly. |
| `extraction_eval` | Provider-free LLM payloads validate, normalize, or reject correctly. |
| `retrieval_privacy_eval` | Sensitive or non-promptable memories are suppressed when needed. |
| `product_replay_eval` | The end-to-end replay remains coherent. |

## Stable Boundaries

| Layer | Current status |
| --- | --- |
| Rule extraction, write policy, use gate, prompt context | Supported local product path. |
| FastAPI endpoints and JSON / SQLite persistence | Supported for prototypes. |
| Review queue, correction, delete, forget-all, audit export | Implemented for governance demos. |
| LLM proposal ingest | Provider-free payload parsing is wired into v2 ingest; provider-backed extraction is future work. |
| Math runtime | Deterministic activation, anomaly, causal relevance, semantic gravity, and retrieval-v3 scoring are local explainable rules. |
| Benchmarks | Deterministic regression seeds, not broad personal-memory benchmark claims. |

## Fit / Non-Fit

Good fit:

| Product | Why |
| --- | --- |
| Personal assistants | Need durable style, events, and correction paths. |
| AI companions | Need adaptation without awkward private recall. |
| Workflow agents | Need memory governance, audit, and prompt-safe context. |
| Long-running sessions | Need stale-memory suppression and forget controls. |

Poor fit:

| Product | Better choice |
| --- | --- |
| Stateless bots | Do not add memory when output should never adapt. |
| Transcript search | Use search or RAG. |
| Uninspectable black-box memory | Use a governed store first. |
| Highly regulated production memory | Add policy review, privacy review, encryption, migrations, and red-team tests before launch. |

## Repository Map

```text
memory_system/   runtime, extraction, gates, retrieval math, context, storage
evals/           deterministic extraction, write, retrieval, ingest, gate, replay evals
tests/           runtime, API, persistence, correction, prompt-safety tests
examples/        runnable replay and product walkthrough
docs/            GitHub Pages product page and design notes
app.py           FastAPI service
demo.py          local extraction demo
```

## Roadmap

| Area | Next step |
| --- | --- |
| Calibration | Add Brier score, expected calibration error, and threshold tuning. |
| Retrieval | Add production embeddings/vector index behind the existing scorer contract. |
| Extraction | Add provider-backed extraction and disagreement checks on top of the wired payload boundary. |
| Privacy | Add sensitive-memory red-team prompts, encryption, retention policy fixtures, and migration tests. |
| Integration | Add chatbot, workflow, and multi-agent harness examples. |

## Security

Do not commit real user transcripts, local SQLite stores, session JSON, API keys,
or debug exports containing personal data. See [SECURITY.md](SECURITY.md).

## License

MIT. See [LICENSE](LICENSE).
