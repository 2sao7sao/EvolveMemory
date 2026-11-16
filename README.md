<img src="assets/readme-banner.png" alt="EvolveMemory — governed memory for AI assistants" width="100%" />

# EvolveMemory

**A local memory runtime that controls what an AI assistant remembers and how it may use it.**

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

## Why EvolveMemory

An assistant can retrieve the right memory and still use it in the wrong way. EvolveMemory separates candidate extraction, write decisions, retrieval, allowed use, and correction so each decision can be inspected.

| Capability | Available scope |
| --- | --- |
| Govern writes | Rule extraction and provider-free LLM payload validation; create, merge, review, reject, or retain only for the current turn. |
| Control use | Gate retrieved memories into direct facts, style policy, follow-up cues, hidden constraints, clarification, summary, or suppression. |
| Correct and inspect | Local JSON / SQLite stores, review queue, correction, deletion, forget-all, and audit export. |
| Reproduce behavior | Offline replay and deterministic regression suites, with inspectable scoring factors. |

This is a research prototype. Production embeddings, provider-backed extraction, host conversation orchestration, and production security are not validated end to end. The authority, scope, lifecycle, and interaction modules have local implementations; their presence does not establish complete integration into every API path.

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

## How it works

```text
user turn → proposals → write governance → local store
query → retrieval → use gate → response policy → prompt context
feedback → correction / retirement → audit
```

<img src="assets/runtime_contract_map_v2.svg" alt="Memory runtime modes: observe, write, retrieve, adapt, correct, and audit" width="100%" />

The use gate controls what enters the prompt; a retrieval score alone never grants permission. Current semantic scoring uses a deterministic hash embedding substitute. See [scoring and API details](docs/runtime-reference.md), [gate rules](docs/gate-decision-rules.md), and the [architecture proposal](docs/next-development-spec.md).

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

The 2026-11-16 [controls/scope implementation slice (PR #15)](https://github.com/2sao7sao/EvolveMemory/pull/15) passed 115 local tests (72 pytest subtests), all 11 deterministic eval suites, and the standalone adaptive replay. PR #15 is merged and its [hosted CI passed](https://github.com/2sao7sao/EvolveMemory/actions/runs/43906016401). These results cover seeded cases and HTTP handlers through FastAPI’s test client. They do not establish a complete host loop, live model helpfulness, retrieval at scale, production latency, or deployed service readiness. The earlier PR #13 baseline checks are recorded separately in [maintenance notes](docs/maintenance.md); see [protocol §13](docs/conversation-memory-invocation-spec.md#13-历史缺口主线修复与本轮状态) for this slice.

## Status and roadmap

**Recommendation: continue maintenance, with correctness and one complete conversation path as the next milestone.**

| Priority | Next step | Completion evidence |
| --- | --- | --- |
| P0 | Preserve normalized-only storage, settings, and scope regressions | PR #15 is merged with passing local checks and hosted CI. |
| P1 | Complete temporary turn scope and the minimal host in [draft PR #12’s protocol](docs/conversation-memory-invocation-spec.md) | Current-turn overrides and actual model-call input capture; local ingest protections alone do not complete S0-c / S1. |
| P1 | Integrate scope, correction, and lifecycle checks into a single-thread loop | Source-backed cases that cover old decisions, opt-out, stale events, and prompt delivery. |
| P2 | Introduce real extraction / embedding providers and measure them | Versioned datasets, provider configuration, costs, latency, and failure cases. |
| P2 | Restore the product-page publishing path | Successful Pages deployment and an independently checked live URL. |

PR #12 now records the confirmed project-task continuation choices and the remaining protocol work. Its historical CI failure came from the migration-clock test fixed in PR #13; new branch checks must use the updated revision. PR #15 delivers the validated controls/scope slice; full S0-c / S1, complete cross-thread retrieval, and real-model helpfulness remain unverified. See [maintenance status](docs/maintenance.md) and the [development spec](docs/next-development-spec.md) for scope and evidence boundaries.

## Documentation and assets

| Resource | Purpose |
| --- | --- |
| [Conversation-memory protocol](docs/conversation-memory-invocation-spec.md) | Confirmed product choices, scoped evidence, delivery capture, and fixed acceptance cases; the full protocol is not complete. |
| [Runtime reference](docs/runtime-reference.md) | Retrieval math, activation, causal relevance, write governance, Python and HTTP surfaces. |
| [Adaptive replay walkthrough](examples/adaptive_memory_replay.md) | Inputs, outputs, and what each seeded check establishes. |
| [Maintenance notes](docs/maintenance.md) | Current evidence, prioritized follow-up, and visual asset inventory. |
| [Positioning](docs/positioning.md) · [Phase 2 design](docs/phase2-optimization-spec.md) | Intended use and proposed future architecture; targets are not measured results. |

## Contributing and related projects

See [CONTRIBUTING.md](CONTRIBUTING.md) and [SECURITY.md](SECURITY.md). Use synthetic examples; keep real transcripts, local stores, credentials, and private debug exports out of commits. Licensed under [MIT](LICENSE).

Related projects: [Agent Peak Bench](https://github.com/2sao7sao/agent-peak-bench) for agent evaluation, [EvolveKB](https://github.com/2sao7sao/EvolveKB) for knowledge workflows, and [Video Analysis Skills](https://github.com/2sao7sao/video-analysis-skills) for structured video analysis. These are separate repositories, not a claim of an integrated product.
