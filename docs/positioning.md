# EvolveMemory positioning

Updated **2026-11-16**, after the user's direction correction. This decision supersedes the earlier same-day rule that every inferred profile needs user confirmation before adaptation.

## Vision

EvolveMemory is a memory and evolving-understanding runtime for AI that gets to know a person through long-term collaboration. It should learn from ordinary conversation, revise its understanding as the person changes, and make that understanding useful without repeatedly asking the user to confirm a profile or recounting old conversations.

The intended experience is an attentive collaborator and companion: it remembers what matters, understands the context, accepts correction, and responds naturally. “Knowing the user” is a product goal to evaluate, not a claim that the current rule engine understands a person's inner life.

**中文定位：**让 AI 在长期相处中自主形成并持续修正对人的理解，区分稳定偏好、阶段变化与具体情境，让对话自然贴合这个人。项目任务续接是首个验证场景；长期协作、陪伴与知己式体验是愿景，尚未由当前原型证明。

## Product decisions

| Decision | Current direction |
| --- | --- |
| First scenario | Continue a project task using its old decisions, current constraints, and unfinished work. This is an initial test bed for a broader long-term relationship. |
| Understanding | Infer from independent, attributable observations over time. Sufficient evidence may update memory and relevant, natural adaptation automatically within the enabled scope. |
| Stability and change | Distinguish a stable default, a persistent change, and a contextual exception. New evidence and direct corrections can weaken, replace, or retire an old inference. |
| Weak evidence | Keep it tentative, gather more evidence, or suppress it. Do not turn every weak signal into a confirmation request. |
| Natural adaptation | Apply relevant style and collaboration preferences quietly. Avoid repeated “I remember…” statements, profile labels, and unrelated old events. |
| User control | Current requests, corrections, deletion, disabled memory, sensitive-data settings, and scope remain effective. Autonomous inference does not grant new access or permission for external actions. |
| Events and explanations | Event follow-ups remain individually enabled. Show sources or uncertainty when needed for an old decision, a changed fact, a conflict, or a user question; ordinary style adaptation needs no repeated provenance recital. |

## Vision, implementation, and evidence

| Level | What is supported |
| --- | --- |
| Merged foundation | PR #15 provides normalized v2 storage, shared read/write controls, scope persistence, event opt-in, source checks, and lifecycle regressions. Its confirmed-only profile rule is historical and is replaced in this locally validated revision. |
| Current U0 implementation | Evidence-backed automatic profile accumulation and adaptation retain source identity, settings, correction, and scope checks. Local validation: 157 tests / 101 pytest subtests, 157 unittest tests, 11 deterministic suites, replay PASS; no provider. Branch `feat/autonomous-understanding-20261116` awaits remote publication and Checks. |
| Present mechanism | Rules and caller-supplied `llm_payload` proposals. A payload accepted by the API is not an integrated model provider. |
| Still missing | A complete multi-turn host, broad stable/change/context reasoning, real-provider evidence, long-term natural-conversation evaluation, and production deployment guarantees. |

The governance layer supports the experience: it controls the use and revision of understanding. A review queue remains useful for policies that explicitly request review; it is not the default interaction loop for ordinary inferred preferences.

## Experience acceptance

Use versioned conversations, captured model-call inputs, final answers, and user feedback. Check these behaviors independently:

1. **Natural adaptation:** after multiple distinct preference signals, a later answer improves in structure without asking for profile confirmation or mentioning the remembered signals.
2. **Correction changes behavior:** after “that is no longer my preference,” the next relevant answer and persisted state change; old evidence does not silently recreate the retired inference.
3. **Context is preserved:** concise work summaries and detailed study explanations can coexist; one does not erase the other or become a global trait.
4. **Change is recognized:** a lasting change can replace an earlier pattern, while “just this once” affects only the current situation.
5. **Memory stays proportionate:** irrelevant events and personal facts remain unused; long-term familiarity does not become repeated reminders or intrusive follow-ups.
6. **Control remains effective:** disabling a layer, removing a source, or narrowing scope changes both retrieval and adaptation.

These are acceptance requirements, not passed results. Project tasks provide the first bounded cases; companionship and a sense of being understood need longitudinal user evaluation beyond deterministic tests.

## Next delivery steps

1. Publish the locally validated U0 slice with its exact revision and remote Checks; keep its rule/API results separate from experience acceptance.
2. Next, add the S1-a minimal host and temporary context / S0-c; capture the exact context delivered to a callable, then test natural adaptation and correction across turns.
3. Extend evidence and context models to distinguish durable patterns, change, and situational variation; evaluate without fitting only seeded phrases.
4. Connect a real provider and run comparative, long-term user evaluation for helpfulness, correction effort, repetition, and unwanted personalization.

See the [development plan](next-development-spec.md), [runtime contract](runtime-reference.md), and [maintenance evidence](maintenance.md). Deployment requirements are tracked in [SECURITY.md](../SECURITY.md).
