<img src="assets/readme-banner.png" alt="EvolveMemory — governed memory for AI assistants" width="100%" />

# EvolveMemory

**A memory runtime for AI that learns about people over time, revises its understanding, and adapts naturally.**

<p align="center">
  <a href="README.zh-CN.md">简体中文</a> ·
  <a href="#quick-start">Quick start</a> ·
  <a href="docs/runtime-reference.md">Docs</a> ·
  <a href="#status-and-roadmap">Roadmap</a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.11%2B-ff5aa5" alt="Python 3.11+" />
  <a href="https://github.com/2sao7sao/EvolveMemory/actions/workflows/ci.yml"><img src="https://github.com/2sao7sao/EvolveMemory/actions/workflows/ci.yml/badge.svg" alt="CI workflow status" /></a>
  <img src="https://img.shields.io/badge/stage-research_prototype-b8eee4" alt="Research prototype" />
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-ff5aa5" alt="MIT license" /></a>
</p>

**Live-trial update:** [Draft PR #17](https://github.com/2sao7sao/EvolveMemory/pull/17) connects a real DeepSeek host. The 24-turn trial recovered old project decisions but failed preference correction internally; [actual excerpts and remaining P0 defects](https://github.com/2sao7sao/EvolveMemory/blob/feat/live-project-continuation-20261116/docs/live-evaluation-results.md) are separate from rule-test success. PR #17 is not merged; historical no-provider claims below describe the PR #16 baseline.

## Why EvolveMemory

Long-term collaboration needs more than recalling facts: an assistant should learn stable preferences, recognize change and context, and respond naturally after correction. EvolveMemory explores that experience with inspectable evidence, memory updates, and controls. Project-task continuation is the first test scenario; long-term collaboration and companionship are the vision.

| Capability | Available scope |
| --- | --- |
| Form and revise understanding | Evidence accumulation and correction exist; this revision enables automatic profile adaptation from independent source turns. The U0 rule and API slice passes local checks; user experience remains unverified. |
| Govern writes | Rule extraction or real-model proposals through validated `llm_payload`; create, merge, review when configured, reject, or retain only for the current turn. |
| Control use | Gate retrieved memories into direct facts, style policy, follow-up cues, hidden constraints, clarification, summary, or suppression. |
| Correct and inspect | Local JSON / SQLite stores, review queue, correction, deletion, forget-all, and audit export. |
| Reproduce behavior | Offline replay and regression suites, plus a bounded DeepSeek conversation host that records actual requests, replies, and memory decisions. |

This research prototype includes a real DeepSeek provider and a bounded multi-turn host, alongside the offline rule runtime. On 2026-11-16 the user replaced the earlier confirmed-only profile rule: supported ordinary preferences should adapt automatically, while weak evidence stays tentative without default confirmation questions. Settings, scope, source validity, and opt-out remain effective. Real-model project continuation is under evaluation; broad stable/change/context reasoning and the intended natural experience are not yet accepted.

## Quick start

Requires Python 3.11+. The replay runs locally without a model API key.

```bash
git clone https://github.com/2sao7sao/EvolveMemory.git
cd EvolveMemory
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m memory_system.demo
```

Expected output includes `status: PASS`, `accepted_candidates: 4/4`, and `gate_eval: 8/8`. These are fixed replay checks, not a production quality score.

To start the prototype API:

```bash
python -m uvicorn app:app --reload
```

Open `http://127.0.0.1:8000/docs` for the API reference. See the [runtime reference](docs/runtime-reference.md#developer-surface) for SQLite configuration and Python usage.

### Live DeepSeek conversation

After installing the dependencies, run the 24-turn **synthetic user script with real `deepseek-flash` responses**. The runner starts its own local API and compares memory-enabled and recent-context-only conversations:

```bash
python examples/run_live_conversation.py \
  --api-key-file /absolute/private/path/deepseek-key.txt \
  --model deepseek-flash \
  --output data/live-runs/run-01
```

Point to an existing private key file; do not copy the key into the repository or command text. The output directory must be new or empty. Defaults are **100 logical provider calls** and a **US$2 estimated-cost guard**, not a provider billing cap; retries and failed calls may also be billed. This command makes paid external model calls. See the [live-run contract](docs/runtime-reference.md#live-deepseek-conversation) for optional arguments, boundaries, and artifacts.

Open `data/live-runs/run-01/transcript.html` or `transcript.md` after the run. Per-turn JSON, `provider_calls.jsonl`, and `manifest.json` preserve the actual delivered context, raw replies, failures, usage, and cost estimate. A completed run is evidence of execution, not acceptance of natural understanding.

## How it works

```text
user turn → proposals → write governance → local store
query → retrieval → use gate → response policy → prompt context
feedback → correction / retirement → audit
```

<img src="assets/runtime_contract_map_v2.svg" alt="Memory runtime modes: observe, write, retrieve, adapt, correct, and audit" width="100%" />

The use gate controls what enters the prompt; a retrieval score alone never grants permission. The live host keeps the last two user/assistant pairs and clears them on session changes. It extracts proposals, validates evidence and retention, writes through v2 governance, retrieves up to 50 governed candidates, asks the model to select at most 10 IDs, then rechecks those IDs through the same governed query and prompt paths before answering. This does not retrieve raw past conversations. The initial candidate ranking still uses a deterministic hash embedding substitute. See [scoring and API details](docs/runtime-reference.md), [gate rules](docs/gate-decision-rules.md), and the [architecture proposal](docs/next-development-spec.md).

## Reproduce the example

The replay writes two synthetic user turns, queries them in different contexts, and applies a correction:

| Input | Expected behavior |
| --- | --- |
| “I am preparing for an interview” and “Start with the conclusion” | Preserve the event and communication preference as separate memories. |
| Ask for interview preparation | Use the event as a follow-up cue and apply the style preference. |
| Ask for a Python review and explicitly exclude the interview | Suppress the interview while retaining allowed style guidance. |
| Ask to stop remembering anxiety | Retire the sensitive state and its derived profile signal. |

This existing replay uses the standalone session runtime. Its follow-up examples do not enable v2 event follow-ups, which default to off per event; see the [v2 contract](docs/runtime-reference.md).

```bash
python examples/replay_adaptive_memory.py
python -m unittest discover -s tests -p 'test_*.py'
python -m evals.runner --suite all
```

The merged [PR #15](https://github.com/2sao7sao/EvolveMemory/pull/15) baseline passed 115 local tests (72 pytest subtests), all 11 deterministic suites, the standalone replay, and [hosted CI](https://github.com/2sao7sao/EvolveMemory/actions/runs/43906016401). Those results cover the earlier controls/scope implementation, including its now-superseded profile-confirmation rule. The subsequent **PR #16 U0 baseline passed 157 local tests (101 pytest subtests), all 11 deterministic suites, and replay PASS**, using an isolated temporary data directory and no provider; see [PR #16](https://github.com/2sao7sao/EvolveMemory/pull/16). Those historical checks do not validate the new live host or establish experience acceptance U01–U08. Real-run transcripts and request traces must be assessed separately for useful recall, correction, and natural adaptation. See [maintenance evidence](docs/maintenance.md).

Latest live trial: 24 turns per arm recovered the old decision and corrected participant scope, but a negated preference reinforced an incorrect profile and state fields failed validation. **Project-fact continuation improved; preference correction failed.** The final code passed 205 tests / 165 subtests and all 11 deterministic suites. See [actual excerpts, every run and priority failures](docs/live-evaluation-results.md); engineering checks do not establish experience acceptance.

## Status and roadmap

**Build toward lasting, revisable understanding; verify it first through project-task collaboration.**

| Priority | Next step | Completion evidence |
| --- | --- | --- |
| U0 — locally checked | Automatic, evidence-backed profile adaptation | Local rules/API regressions pass; remote publication and user-experience acceptance remain separate. |
| S1-a / S0-c — under evaluation | Real-provider bounded host, temporary retention, and governed model selection are implemented | Inspect delivered input and subsequent answers for current-request priority, correction, and scope; implementation is not experience acceptance. |
| S1 experience | A useful project-task continuation | Recover old decisions, change after correction, and avoid repetitive reminders or irrelevant events. |
| S2–S4 | Lasting understanding and longitudinal real-model evaluation | Distinguish stable preferences, persistent change, and contextual exceptions; measure helpfulness and correction effort over time. |

[Draft PR #12](https://github.com/2sao7sao/EvolveMemory/pull/12) records the revised direction and remaining protocol. The first project scenario does not reduce the vision to task tracking. See [positioning](docs/positioning.md), the [development plan](docs/next-development-spec.md), and [experience acceptance U01–U08](docs/next-development-spec.md#fixed-experience-acceptance) for the distinction between vision, implementation, and unverified behavior.

## Documentation and assets

| Resource | Purpose |
| --- | --- |
| [Conversation-memory protocol](docs/conversation-memory-invocation-spec.md) | Autonomous understanding, source/scope boundaries, delivery capture, and fixed experience acceptance; the full protocol is not complete. |
| [Runtime reference](docs/runtime-reference.md) | Retrieval math, activation, causal relevance, write governance, Python and HTTP surfaces. |
| [Adaptive replay walkthrough](examples/adaptive_memory_replay.md) | Inputs, outputs, and what each seeded check establishes. |
| [Maintenance notes](docs/maintenance.md) | Current evidence, prioritized follow-up, and visual asset inventory. |
| [Positioning](docs/positioning.md) · [Phase 2 design](docs/phase2-optimization-spec.md) | Intended use and proposed future architecture; targets are not measured results. |

## Contributing and related projects

See [CONTRIBUTING.md](CONTRIBUTING.md) and [SECURITY.md](SECURITY.md). Use synthetic examples; keep real transcripts, local stores, credentials, and private debug exports out of commits. Licensed under [MIT](LICENSE).

Related projects: [Agent Peak Bench](https://github.com/2sao7sao/agent-peak-bench) for agent evaluation, [EvolveKB](https://github.com/2sao7sao/EvolveKB) for knowledge workflows, and [Video Analysis Skills](https://github.com/2sao7sao/video-analysis-skills) for structured video analysis. These are separate repositories, not a claim of an integrated product.
