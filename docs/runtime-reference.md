# EvolveMemory runtime reference

[Back to the README](../README.md) · [中文](runtime-reference.zh-CN.md)

These formulas and interfaces describe the deterministic prototype. Module presence does not establish a complete hosted conversation loop or measured real-model improvements.

## Automatic understanding revision: 2026-11-16

The user superseded the earlier confirmed-only profile decision on 2026-11-16. The current direction is autonomous, revisable understanding from independent evidence: supported ordinary preferences can adapt the response without a per-profile confirmation step. Weak evidence remains tentative or unused rather than automatically generating a question. The aim is natural long-term collaboration; project tasks are the first scenario.

This revision's U0 implementation passed local rules/API checks: **157 pytest tests + 101 subtests**, **157 unittest tests**, **11/11 deterministic suites** (`failures=[]`), and **replay PASS**, using an isolated temporary data directory without provider calls. Implementation and hosted Checks are tracked in [PR #16](https://github.com/2sao7sao/EvolveMemory/pull/16). The historical PR #15 results remain separate. Rules and externally supplied `llm_payload` still provide proposals; no integrated real provider or complete multi-turn host experience is established.

| Aspect | Revised contract |
| --- | --- |
| Promotion | Multiple independent, usable source turns may support automatic profile storage and relevant, natural style adaptation. No universal `user_review_approved` requirement. Model confidence alone and repeated copies of one turn are insufficient. |
| Revision | Explicit correction and counter-evidence can weaken, replace, or retire an inference. Stable defaults, persistent change, and contextual exceptions must be distinguished; broad coverage of these cases remains an acceptance goal. |
| Weak evidence | Keep provisional or suppress; do not require the user to verify every uncertain impression. Clarify only when a material current ambiguity warrants it. |
| Natural use | Apply relevant preferences without profile labels, repeated provenance recitals, or unrelated reminders. Explain the inference when asked, or when a changed fact/conflict needs context. |
| Controls | Scope, source validity, disabled keys/layers, `allow_inferred_profile`, sensitive-data policy, and master opt-out still constrain accumulation and use. |
| Review | Explicitly configured review and sensitive/restricted policies remain available. Ordinary evidence-backed profile adaptation does not wait for a review marker by default. |

See [experience acceptance U01–U08](next-development-spec.md#fixed-experience-acceptance). These are requirements, not evidence that real responses already feel natural.

### Candidate implementation details and limits

The following U0 behavior is implemented and covered by the local checks above. Experience acceptance U01–U08 remains uncompleted; the next step is S1-a minimal host and temporary context:

| Mechanism | Current behavior and boundary |
| --- | --- |
| Server qualification | The server can attach `metadata.profile_qualification={"policy_version":"autonomous-v1","method":"scoped_turn_evidence","distinct_turn_count":N}` only from its controlled live evidence pool. An external `llm_payload` claiming this marker does not grant qualification. |
| Bounded evidence rule | At least **2 distinct real source turns**, net support **≥ 1.2**, the most recent **8 turns per dimension**, and a **30-day half-life** without a permanent weight floor. Ties do not select a winner. These are engineering heuristics, not measured psychological or model-quality thresholds. |
| Read-time re-evaluation | Query and prompt-context recompute qualification against the current clock and live sources in the same scope. A profile can stop being used as support decays or becomes unavailable even without another ingest. This is read-time suppression, not proof of complete dependency cleanup or concurrent revocation. |
| Review defaults and migration | `review_required_for_layers=[]`. Old settings without an explicit marker whose list is exactly `["inferred_profile"]` move to the automatic default; the old list and migration reason are retained in `legacy_review_required_for_layers` and `review_policy_migration`. The old schema cannot distinguish that historical default from a manual choice of the identical list; the migration records this ambiguity. New PUT requests that set the review field mark `review_required_for_layers_explicit=true`; explicit policies are retained. |
| Ingest retry identity | Optional `turn_id` lets a host reuse the same source-turn identity for a retry. If omitted, each request receives a new identity. Do not claim default request idempotence; hosts must supply stable IDs when they need retry deduplication. |
| Direct profile correction | Explicit `POST /v2/users/{user_id}/memory/{memory_id}/correct` creates new user-provided evidence for the corrected value. The old inference sources stay with the old version/audit; they must not continue filtering the corrected value through the old evidence pool. Compiled response policy and prompt instructions must also use the corrected value, without retaining an old high-value instruction. This does not fabricate `user_review_approved`. Current settings and scope still apply. |
| Current-turn override | Both context routes recognize a finite set of current preference overrides, suppress conflicting older style for that query, and do not persist the override as a long-term preference. Negation, quoted text, and broader contextual reasoning remain bounded by the rules. |
| Natural-style prompting | Prompt instructions encourage applying preferences without reciting profile labels or recalling old events to demonstrate memory. No response-history repetition controller or measured natural-conversation guarantee is established. |

## Controls and scope foundation: PR #15

This section records the **PR #15 controls/scope foundation**. The profile policy is revised above; the remaining storage and scope boundaries are retained. A complete S1 host, real-model calls, delivery receipts, and concurrent-revocation guarantees remain incomplete. These are local prototype boundaries, not verified production authentication or tenant isolation.

Local results on 2026-11-16: pytest **115 passed, 72 subtests passed**; unittest **115 passed**; deterministic evals **11/11**, with no failures; adaptive replay **PASS**. Independent local review found no blocker within this slice. These historical results belong to [PR #15](https://github.com/2sao7sao/EvolveMemory/pull/15), merged at `8e3ab17` with [passing CI](https://github.com/2sao7sao/EvolveMemory/actions/runs/43906016401). They do not validate this revision’s automatic-understanding change.

### One v2 storage and read path

The normalized repository is the only v2 source of reads and writes. `turns/ingest` no longer dual-writes to the legacy session store; `memory/query` and `prompt-context` never implicitly fall back to old `/sessions` data. Existing session data stays intact and is not moved automatically. An application can explicitly invoke the existing `NormalizedSQLiteMemoryRepository.migrate_store(store=..., user_id=..., session_id=..., now=...)` when migration is intended. The old session API and the standalone Python example below do not provide v2 user-settings governance.

Both v2 read endpoints use `prepare_v2_query`. Scoped selection and `apply_read_controls` filter keys, layers, sensitive records, and profiles before ranking, candidate/debug output, and context compilation. Relevance cannot restore a disabled record. Writes also use current settings; temporary instructions, `auto_write=false`, or master-off must not create derived profile evidence.

### Fields, scope, and project enablement

| Surface / field | Implemented semantics |
| --- | --- |
| Ingest `turn_id` | Optional source identity. Reuse it for a host retry; omission creates a new identity per request, not default idempotence. |
| Ingest `session_id`, `project_id`, `domain` | Current context supplied by the trusted host, not authorization inferred from query text. |
| Ingest `memory_scope` | `turn/session/project/domain/global`; defaults to `session`. Natural language can narrow to temporary turn/session scope, never authorize broader sharing. |
| Query / prompt-context `session_id`, `project_id`, `domain` | Session records match session and project exactly. `None` means an unbound value, not all records for a user. |
| Settings `enabled_project_ids` | Defaults to `[]`; project-scope reads and writes require that project to be enabled. |
| Settings `allow_global_memory` | Defaults to `false`; global-scope reads and writes require explicit enablement. |
| Domain scope | Requires an explicit domain; when a project is supplied, that project must also be enabled. |

An enabled project allows its project-scoped **records** to be reused from another session in the same project. This is not a cross-thread source-history index or full conversation retrieval system. Omitting session/project identifiers does not request a user-wide search.

For example, the host first saves settings with `PUT /v2/users/{user_id}/memory/settings`:

```json
{"enabled_project_ids": ["project-A"], "allow_global_memory": false}
```

Then it ingests a project-A record:

```json
{
  "session_id": "thread-A1",
  "project_id": "project-A",
  "memory_scope": "project",
  "text": "记住，回答直接一点，先给结论。"
}
```

A later same-project query can use `{"session_id":"thread-A2","project_id":"project-A","query":"在本项目中怎么回答代码 review 问题？"}`. `project-B` or an unbound project does not inherit access to A. Relevance or the word “global” in a message does not enable sharing.

### Profile evidence, event follow-ups, and revalidation

- Under the revised default, a profile can adapt automatically when independent evidence satisfies the inference policy and current settings/scope permit use. The old universal `metadata.user_review_approved=true` requirement from PR #15 is superseded; manual approval can still exist when explicitly configured. Disabled, stale, deleted, or out-of-scope support cannot be reintroduced through a profile. The local checks cover this rule/API behavior; they do not prove broad contextual understanding or natural responses.
- Event follow-ups are off by default per event. `PUT /v2/users/{user_id}/memory/events/{memory_id}/followup` with `{"enabled":true}` enables one event; `{"enabled":false}` disables it. Global `allow_event_followup` and current record controls still apply. Enabling the global switch does not opt in every event.
- Review resolution rechecks settings when approval is requested. If key/layer/sensitivity/project/global permission has been withdrawn since queuing, it returns **409** and preserves **pending** rather than marking the item approved first.
- Correction accepts ACTIVE targets only. Deletion and forget-all cancel related pending reviews. Approval rechecks target/source state, scope, settings, and time so a queued proposal cannot revive a deleted or expired source.
- Profile evidence uses real record IDs and deduplicates by source turn. Distinct turns attached to a merged record remain distinguishable; repeating a source does not become new evidence. Fixed tests cover lossless migration of the old record schema and profile-evidence uniqueness constraint.
- Reading an event as relevant factual background is separate from permission to proactively follow up. This slice does not provide user-delivery receipts, concurrent quotas, or revocation of an in-flight generation.

## Mathematical Runtime

EvolveMemory treats memory behavior as a scored, inspectable decision chain.
Rules are deterministic today, but each important module emits factors,
weights, formulas, rationale, and a version so it can later be calibrated or
learned from feedback.

`ScoreBreakdown` is the common explanation object:

| Field | Example value |
| --- | --- |
| `name` | `retrieval` |
| `score` / `probability` | $0.81$ |
| `factors` | $K=0.50,\ A=0.72,\ G=0.88$ |
| `weights` | $w_K=0.22,\ w_A=0.14,\ w_G=0.06$ |
| `formula` | $S_{\mathrm{ret},v3}$ |
| `rationale` | Career query depends on current work or event state. |
| `version` | `retrieval-v3.0` |

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

Retrieval ranks candidates. It still does not grant permission. The v2 settings and scope filters run before these scores; only permitted candidates are ranked.

```math
\begin{aligned}
S_{\mathrm{ret},v3}
= \mathrm{clamp}\big(&
0.22K_{\mathrm{keyword}}
+ 0.22E_{\mathrm{embedding}}
+ 0.14F_{\mathrm{freshness}}\\
&+ 0.14L_{\mathrm{layer}}
+ 0.14A_{\mathrm{activation}}
+ 0.08C_{\mathrm{causal}}\\
&+ 0.06G_{\mathrm{gravity}}
\big)
\end{aligned}
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

```math
\begin{aligned}
\ell_A
&= b_{\mathrm{lifecycle}}
+ \log(c_{\mathrm{confidence}})
- \lambda_{\mathrm{lifecycle}}a_{\mathrm{days}}\\
&\quad
+ \rho\log(1+r_{\mathrm{count}})
+ \alpha Z_{\mathrm{temporal}}
- \phi f_{\mathrm{fatigue}},\\
A_{\mathrm{activation}}
&= \sigma(\ell_A).
\end{aligned}
```

The anomaly input is derived before activation:

```math
Z_{\mathrm{temporal}}
= 0.50D_{\mathrm{duration}}
+ 0.30R_{\mathrm{recurrence}}
+ 0.20Q_{\mathrm{severity}}.
```

This separates ordinary recency from persistent state risk: a normal preference
can quietly remain long term, while a recurring volatile state can stay visible
for careful follow-up or review.

<img src="../assets/activation_model_v2.svg" alt="State temporal anomaly model with TTL, recurrence, anomaly score, and phase transitions" width="100%" />

### 3. Semantic Gravity

Semantic gravity prevents important life or safety context from being lost just
because lexical overlap is weak. Job loss, interviews, exams, health
constraints, relationship transitions, and persistent emotional state can
matter more than a generic preference.

```math
\begin{aligned}
G_{\mathrm{social}}
&= \mathrm{clamp}\!\left(
g_{\mathrm{base}}(k,v)
\cdot w_{\mathrm{culture}}
\cdot m_{\mathrm{life\ stage}}
\right),\\
G_{\mathrm{final}}
&= \mathrm{clamp}\!\left(
\frac{
G_{\mathrm{social}}\left(1+0.35I_{\mathrm{personal}}\right)
}{
1+0.50F_{\mathrm{fatigue}}
}
\right).
\end{aligned}
```

Semantic gravity is not permission either. It only prevents high-impact context
from disappearing before the use gate can decide whether it should be mentioned,
hidden, summarized, or suppressed.

<img src="../assets/semantic_gravity_model_v2.svg" alt="Semantic gravity model with context resolution, social gravity, and individual modulation" width="100%" />

### 4. Causal Relevance

Causal retrieval asks: would this memory change the safe or useful answer?

```math
C(m,q)=R(m,q)
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

<img src="../assets/write_governance_model_v2.svg" alt="Write governance model with proposal boundary, weighted score, hard policy, and decision paths" width="100%" />

Write governance uses a weighted score:

```math
\begin{aligned}
S_{\mathrm{write}}
= \mathrm{clamp}\big(&
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
| `review` | An explicit review policy or sensitive/restricted rule needs user input. Ordinary weak profile evidence stays tentative or unused; it does not inherently request confirmation. |
| `merge` | Duplicate evidence should attach to an existing record. |
| `supersede` | A higher-or-equal authority candidate replaces an exclusive conflicting value. |
| `reject` | Settings, explicit refusal, hard confidence floor, or low weighted utility blocks the write. |

## Memory-Use Gate And Prompt Safety

The gate turns ranked candidates into allowed actions.

```math
\begin{aligned}
S_{\mathrm{gate}}
= \mathrm{clamp}\big(&
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
```

The gate is not another retrieval score. It separates usefulness from
visibility: a high-scoring memory may still become `style_only`,
`summarize_only`, or `suppress` because of privacy, allowed-use constraints,
explicit suppression, or sensitive-memory policy.

| Gate action | Prompt channel |
| --- | --- |
| `use_directly` | Direct user facts, only when safe to mention. |
| `style_only` | Style policy without exposing raw private evidence. |
| `follow_up` | At most one short progress cue for an individually opted-in event, subject to global settings, state, and cooldown. |
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

Standalone session-runtime example (not the v2 user-governance surface; v2 project permissions are not applied automatically):

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
| `POST /v2/users/{user_id}/memory/review-queue/{review_id}/resolve` | Resolve against current settings; revoked permission returns 409 and leaves the item pending. |
| `PUT /v2/users/{user_id}/memory/settings` | Set master, project/global, key/layer, and feature controls. |
| `PUT /v2/users/{user_id}/memory/events/{memory_id}/followup` | Enable or disable one event with `{"enabled": true/false}`. |
| `POST /v2/users/{user_id}/memory/{memory_id}/correct` | Correct and retire conflicting records. |
| `POST /v2/users/{user_id}/memory/forget-all` | Clear memory with audit trail. |
| `GET /v2/users/{user_id}/memory/audit/export` | Export records, settings, events, and audit data. |
