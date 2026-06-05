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
  -> authority & scope resolution
  -> write governance
  -> normalized store
  -> lifecycle / staleness engine
  -> retrieval plan
  -> hybrid math score
  -> memory-use gate
  -> response policy
  -> memory interaction layer
  -> prompt-safe context + dynamic controls + audit trace
  -> correction / audit / evals
```

<img src="assets/runtime_contract_map_v2.svg" alt="EvolveMemory runtime modes: observe, write, retrieve, adapt, correct, audit" width="100%" />

| Runtime boundary | Contract |
| --- | --- |
| Observe | Extract candidates from a turn or provider-free LLM payload. |
| Authority | Resolve whether a memory is explicit command, stated fact, behavioral signal, or inference. |
| Scope | Determine if memory applies to turn, session, project, domain, or global. |
| Govern | Validate, score, review, reject, merge, supersede, or mark as ephemeral-only. |
| Store | Keep normalized records, evidence, event states, settings, and audit logs. |
| Lifecycle | Track activation, staleness, fatigue, and retirement transitions. |
| Retrieve | Rank candidates by intent, relevance, lifecycle, causal impact, and semantic gravity. |
| Gate | Decide allowed use: direct, style-only, follow-up, clarify, hidden, summary, suppress. |
| Interact | Generate dynamic controls (confirm, scope-select, exception, audit) based on uncertainty. |
| Compile | Produce prompt-safe sections rather than raw private memory injection. |
| Correct | Retire, delete, forget-all, or export audit evidence. |

## What Ships In This Repo

| Surface | What it gives you |
| --- | --- |
| Memory runtime | Deterministic local engine for ingest, retrieval, gating, prompt context, correction, and audit. |
| Authority & Scope | Resolver that distinguishes explicit commands from inferences, and turn-scoped from global preferences. |
| Interaction layer | Dynamic controls (confirm, scope-select, exception, audit) generated from memory uncertainty. |
| Lifecycle engine | Staleness scoring, fatigue tracking, and lifecycle transitions (active → stale → retired). |
| FastAPI service | v2 endpoints for turn ingest, memory query, prompt context, review queue, correction, forget-all, and export. |
| Math model | Inspectable scoring objects for retrieval, activation, semantic gravity, causal relevance, and write decisions. |
| Governance | Write policy with ephemeral-only and negative-preference decisions, sensitivity checks, review paths, and audit. |
| Evals | Regression suites for extraction, write decisions, gate actions, privacy, prompt safety, and replay coherence. |
| Product docs | Positioning, gate decision rules, design review notes, and development spec. |

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

`ScoreBreakdown` is the common explanation object, expressed as a structured
math record:

$$
\operatorname{ScoreBreakdown}_{\mathrm{retrieval}} =
\left\{
\begin{aligned}
\operatorname{score} &= 0.81,\\
\operatorname{factors} &= \{K=0.50,\ A=0.72,\ G=0.88\},\\
\operatorname{weights} &= \{w_K=0.22,\ w_A=0.14,\ w_G=0.06\},\\
p &= 0.81,\\
\operatorname{formula} &= S_{\mathrm{ret},v3},\\
\operatorname{rationale} &= \text{career query depends on current work or event state},\\
\operatorname{version} &= \text{retrieval-v3.0}.
\end{aligned}
\right.
$$

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

$$
\begin{aligned}
S_{\mathrm{ret},v3}
= \operatorname{clamp}\big(&
0.22K_{\mathrm{keyword}}
+ 0.22E_{\mathrm{embedding}}
+ 0.14F_{\mathrm{freshness}}\\
&+ 0.14L_{\mathrm{layer}}
+ 0.14A_{\mathrm{activation}}
+ 0.08C_{\mathrm{causal}}\\
&+ 0.06G_{\mathrm{gravity}}
\big)
\end{aligned}
$$

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

$$
\begin{aligned}
\ell_A
&= b_{\mathrm{lifecycle}}
+ \log(\operatorname{confidence})
- \lambda_{\mathrm{lifecycle}}\operatorname{age}_{\mathrm{days}}\\
&\quad
+ \rho\log(1+\operatorname{recurrence}_{\mathrm{count}})
+ \alpha Z_{\mathrm{temporal}}
- \phi\operatorname{fatigue},\\
A_{\mathrm{activation}}
&= \sigma(\ell_A).
\end{aligned}
$$

The anomaly input is derived before activation:

$$
Z_{\mathrm{temporal}}
= 0.50D_{\mathrm{duration}}
+ 0.30R_{\mathrm{recurrence}}
+ 0.20Q_{\mathrm{severity}}.
$$

This separates ordinary recency from persistent state risk: a normal preference
can quietly remain long term, while a recurring volatile state can stay visible
for careful follow-up or review.

<img src="assets/activation_model_v2.svg" alt="State temporal anomaly model with TTL, recurrence, anomaly score, and phase transitions" width="100%" />

### 3. Semantic Gravity

Semantic gravity prevents important life or safety context from being lost just
because lexical overlap is weak. Job loss, interviews, exams, health
constraints, relationship transitions, and persistent emotional state can
matter more than a generic preference.

$$
\begin{aligned}
G_{\mathrm{social}}
&= \operatorname{clamp}\!\left(
g_{\mathrm{base}}(k,v)
\cdot w_{\mathrm{culture}}
\cdot m_{\mathrm{life\ stage}}
\right),\\
G_{\mathrm{final}}
&= \operatorname{clamp}\!\left(
\frac{
G_{\mathrm{social}}\left(1+0.35I_{\mathrm{personal}}\right)
}{
1+0.50F_{\mathrm{fatigue}}
}
\right).
\end{aligned}
$$

Semantic gravity is not permission either. It only prevents high-impact context
from disappearing before the use gate can decide whether it should be mentioned,
hidden, summarized, or suppressed.

<img src="assets/semantic_gravity_model_v2.svg" alt="Semantic gravity model with context resolution, social gravity, and individual modulation" width="100%" />

### 4. Causal Relevance

Causal retrieval asks: would this memory change the safe or useful answer?

$$
C(m,q)=R_{\mathrm{risk\ or\ dependency}}(m,q).
$$

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

$$
\begin{aligned}
S_{\mathrm{write}}
= \operatorname{clamp}\big(&
0.18C_{\mathrm{confidence}}
+ 0.16R_{\mathrm{reuse}}
+ 0.14P_{\mathrm{personalization}}\\
&+ 0.12T_{\mathrm{stability}}
+ 0.10A_{\mathrm{authority}}
+ 0.10E_{\mathrm{evidence}}\\
&+ 0.08N_{\mathrm{novelty}}
+ 0.07U_{\mathrm{actionability}}
+ 0.05V_{\mathrm{privacy}}
\big)
\end{aligned}
$$

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

$$
\begin{aligned}
S_{\mathrm{gate}}
= \operatorname{clamp}\big(&
0.22Q_{\mathrm{relevance}}
+ 0.14F_{\mathrm{freshness}}
+ 0.14A_{\mathrm{authority}}\\
&+ 0.16U_{\mathrm{utility}}
+ 0.14P_{\mathrm{privacy}}
+ 0.08M_{\mathrm{preference}}\\
&+ 0.06T_{\mathrm{token}}
+ 0.06D_{\mathrm{contradiction}}
\big)
\end{aligned}
$$

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
memory_system/           runtime, extraction, gates, retrieval math, context, storage
  governance/            authority resolver, scope resolver
  interaction/           dynamic controls, intervention decider
  lifecycle/             staleness engine, lifecycle transitions
evals/                   deterministic extraction, write, retrieval, ingest, gate, replay evals
tests/                   runtime, API, persistence, correction, prompt-safety tests
examples/                runnable replay and product walkthrough
docs/                    positioning, gate rules, design notes, development spec
app.py                   FastAPI service
demo.py                  local extraction demo
```

## Roadmap

| Area | Next step |
| --- | --- |
| Extraction | Provider-backed LLM extraction with schema validation and repair. |
| Authority & Scope | Expand scope resolution with multi-turn context and behavioral accumulation. |
| Lifecycle | Add retention policy jobs, fatigue-based follow-up suppression, and clarify triggers. |
| Interaction | End-to-end integration of dynamic controls into prompt-context response. |
| Storage | Cross-session PostgreSQL + pgvector backend with migration CLI. |
| Retrieval | Production embeddings, graph expansion, reranker, and usefulness feedback. |
| Governance UX | Minimal dashboard for memory inspection, batch review, and settings. |
| Security | Auth, tenant isolation, encryption, retention enforcement, red-team tests. |
| Evals | 500+ cases covering authority/scope, staleness, interaction, and multilingual scenarios. |

## Prototype Boundary

> **This repository is a research prototype, not a hardened production service.**
>
> Production deployment requires: authentication, tenant isolation, field-level encryption,
> retention policy enforcement, observability, and security red-team testing.
> See [SECURITY.md](SECURITY.md) and [docs/positioning.md](docs/positioning.md).

## Security

Do not commit real user transcripts, local SQLite stores, session JSON, API keys,
or debug exports containing personal data. See [SECURITY.md](SECURITY.md).

## License

MIT. See [LICENSE](LICENSE).
