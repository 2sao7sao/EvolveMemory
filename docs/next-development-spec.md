# EvolveMemory Next Development Spec v0.3

Updated **2026-11-16** after the user's direction correction. The earlier confirmed-only profile decision is superseded: AI should autonomously develop and revise its understanding from evidence, then adapt naturally within existing controls. The new U0 implementation slice passed local checks; implementation and hosted Checks are tracked in [PR #16](https://github.com/2sao7sao/EvolveMemory/pull/16). PR #15 results describe its earlier baseline.

## Product direction

The goal is long-term collaboration and companionship in which an AI increasingly understands a person, distinguishes stable preferences from change and context, and reduces repeated explanations. Project-task continuation is the first bounded scenario, not the whole product vision. See [positioning](positioning.md).

Supported ordinary preferences should shape responses without a confirmation ritual or repeated reminders of past conversations. Weak evidence stays tentative or unused; a useful clarification is reserved for a current answer that materially depends on an unresolved ambiguity. Current instructions, corrections, settings, source availability, and scope constrain every inference and use.

## Target architecture

```text
user turns / app events / explicit corrections
    → source identity + context + time
    → rule or model proposals
    → evidence accumulation / counter-evidence / scope checks
    → revisable understanding: stable default / change / contextual exception
    → governed storage and lifecycle
    → scoped retrieval + memory-use gate
    → natural response policy + optional source explanation
    → host delivery + observed feedback
```

The full architecture is a target. The present extractor uses rules and external `llm_payload`; it does not call a real provider. The host and broad stable/change/context reasoning remain incomplete. [Conversation protocol](https://github.com/2sao7sao/EvolveMemory/pull/12) defines the proposed read path and acceptance matrix.

## Current decisions

- Independent, usable multi-turn evidence can support automatic storage and relevant, natural adaptation. A user-review marker is no longer a universal requirement for inferred profiles.
- Explicit preferences and corrections take priority. Direct profile `/correct` supplies new user evidence; old inference sources stay on the old version/audit and do not filter the corrected value through the old pool. It does not pretend a review was approved. Temporary requests do not become global traits, and contradictory evidence can revise earlier understanding.
- Weak signals do not automatically trigger confirmation. Repeated extraction, model paraphrases, or retrieval of one source do not count as independent observations.
- Natural adaptation uses the preference where relevant; it does not announce a profile or bring up old events just to demonstrate memory.
- Same-project authorized reuse, per-event follow-up opt-in, conditional source hints, settings, and source/scope boundaries remain in force. Understanding someone does not expand access or authorize actions.

## Implementation and evidence

| Layer | Current status | Boundary |
| --- | --- | --- |
| Storage and controls | [PR #15](https://github.com/2sao7sao/EvolveMemory/pull/15) merged at `8e3ab17`; 115 local tests, 72 pytest subtests, 11 deterministic suites, replay PASS; [hosted CI passed](https://github.com/2sao7sao/EvolveMemory/actions/runs/43906016401) | This historical slice included the now-superseded confirmed-only profile rule. Its counts do not validate the new automatic-understanding behavior. |
| Automatic understanding | Implemented candidate: server-qualified `autonomous-v1` from ≥2 real turns; live evidence re-evaluation, bounded decay, finite current-query overrides | Local U0 checks pass. Optional `turn_id` supports host-managed retry identity; broad contextual understanding and response-history repetition control remain unproven. |
| Extraction and retrieval | Rules, external proposal payload validation, deterministic hash embedding substitute | Real extraction/embedding providers and full-history coverage remain unverified. |
| Conversation delivery | Context compilation and HTTP surfaces exist | Complete host orchestration, model-call capture, delivery receipts, and longitudinal experience remain pending. |

### Current local validation

On 2026-11-16, implementation branch `feat/autonomous-understanding-20261116` passed **157 pytest tests + 101 subtests**, **157 unittest tests**, **11/11 deterministic eval suites** (`failures=[]`), and **adaptive replay PASS**, using an isolated temporary data directory without a provider call. Implementation and hosted Checks are tracked in [PR #16](https://github.com/2sao7sao/EvolveMemory/pull/16).

The local U0 rules/API slice is complete. Experience acceptance U01–U08 remains open: tests of state, evidence, and compiled policy do not establish natural multi-turn answers. The next delivery step is **S1-a minimal host plus temporary context / S0-c**, followed by observed response and user-experience evaluation. Commands and evidence are recorded in [maintenance](maintenance.md).

## Development stages

| Slice | Deliverable | Acceptance |
| --- | --- | --- |
| S0-a/b foundation | Normalized-only reads/writes, consistent settings, persisted exact scope, explicit migration | Retain PR #15 regression coverage; no implicit legacy access or scope expansion. |
| U0 automatic understanding | Accumulate independent evidence and automatically adapt supported preferences; allow correction and contradictory evidence to revise the inference | No mandatory confirmation for ordinary supported profiles; duplicate/invalid sources cannot create confidence; weak evidence does not cause unsolicited questions. |
| S0-c context and temporary scope | Current-turn override, current-materials-only, no-write mode, no temporary-to-global escalation | Verify both actual delivered context and persisted state across successive turns. |
| S1-a minimal host | Capture the actual input delivered to a replaceable model callable | Compilation, delivery, generated answer, and sent answer are distinct; deterministic callable results are not provider evidence. |
| S1-b first experience | Project-task continuation with natural preference adaptation and correction across turns | Old decisions remain source-backed; the assistant changes after correction and avoids unnecessary memory recitals. |
| S2 lasting understanding | Stable defaults, evolving preferences, contextual variation, broader authorized history | Diverse changes/contexts and stale-source cases; neither single exceptions nor old habits dominate automatically. |
| S3 feedback and lifecycle | Full dependency invalidation, concurrent revocation, calibrated confidence, event receipts | Versioned evidence, corrections, suppression, and delivery outcomes remain consistent. |
| S4 real provider and experience | Provider integration plus comparative and longitudinal user evaluation | Measure helpfulness, correction effort, naturalness, unwanted recall, latency, and cost; publish failures and limits. |

## Fixed experience acceptance

| ID | Scenario | Required observation |
| --- | --- | --- |
| U01 | Distinct turns show a stable preference; a later related task arrives | Appropriate style adaptation, no mandatory confirmation, no “I remember…” boilerplate. |
| U02 | User corrects an inferred preference | The next relevant answer changes and the old inference is revised; stale evidence does not restore it. |
| U03 | Work summaries should be brief; study explanations should be detailed | Contextual preferences coexist and apply to the matching task. |
| U04 | Compare “this time, be brief” with a sustained new pattern | Temporary override stays local; a lasting change can revise the default. |
| U05 | A weak or duplicated signal appears | No unsupported profile is applied and no unnecessary confirmation prompt is generated. |
| U06 | An unrelated event or personal fact is retrievable | The answer stays on task without recalling it or asking an unsolicited follow-up. |
| U07 | A supporting source expires, is deleted, or becomes out of scope | The derived adaptation cannot carry that excluded information into either context path. |
| U08 | User asks why the assistant adapted | It explains the inference, uncertainty, and available sources without pretending it was explicitly confirmed. |

U01–U08 are requirements, not passed cases. Unit tests check state and policy; captured host inputs check delivery; final responses and user feedback check the experience. No layer substitutes for the next.

## Evaluation and remaining gaps

Track unsupported adaptation, correction residue, context confusion, repeated memory mentions, unnecessary questions, useful adaptation, and user-reported effort. Use the same tasks/model with recent-context-only and memory-enabled variants; include counterexamples and blinded review. Numerical quality and latency targets need baselines and agreed datasets before acceptance.

The old numbered work-package list was a design sequence, not GitHub PR numbers. PR #12 remains the protocol draft, PR #13 repaired the read opt-out and migration clock, and PR #15 delivered controls/scope. Full S0-c, all dependent-record invalidation, concurrent revocation, S1 multi-turn delivery, real-provider quality, and production readiness are still open.
