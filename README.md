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

```bash
python examples/replay_adaptive_memory.py
python -m unittest discover -s tests -p 'test_*.py'
python -m evals.runner --suite all
```

The 2026-11-16 maintenance check passed 72 local tests and all 11 deterministic eval suites after two targeted fixes. It covers the seeded cases and HTTP handlers through FastAPI's test client. It does not establish live model helpfulness, retrieval at scale, production latency, or deployed service readiness. Full evidence and the previous failure are in [maintenance notes](docs/maintenance.md).

## Status and roadmap

**Recommendation: continue maintenance, with correctness and one complete conversation path as the next milestone.**

| Priority | Next step | Completion evidence |
| --- | --- | --- |
| P0 | Keep memory opt-out effective on both v2 read routes; preserve deterministic migration tests | Regressions for normalized storage, legacy fallback, re-enable behavior, and expiry boundaries. Included in this maintenance update. |
| P1 | Review [draft PR #12](https://github.com/2sao7sao/EvolveMemory/pull/12) and agree on the host contract | Explicit decisions for scope and conversation defaults, then an independently tested first slice. |
| P1 | Integrate scope, correction, and lifecycle checks into a single-thread loop | Source-backed cases that cover old decisions, opt-out, stale events, and prompt delivery. |
| P2 | Introduce real extraction / embedding providers and measure them | Versioned datasets, provider configuration, costs, latency, and failure cases. |
| P2 | Restore the product-page publishing path | Successful Pages deployment and an independently checked live URL. |

PR #12 is a discussion draft, not shipped runtime behavior. Its last observed CI run failed on the pre-existing clock-dependent migration test. The local fix here does not rerun or approve that PR. See [maintenance status](docs/maintenance.md) and the [development spec](docs/next-development-spec.md) for the remaining governance UI, storage, and security work.

## Documentation and assets

| Resource | Purpose |
| --- | --- |
| [Runtime reference](docs/runtime-reference.md) | Retrieval math, activation, causal relevance, write governance, Python and HTTP surfaces. |
| [Adaptive replay walkthrough](examples/adaptive_memory_replay.md) | Inputs, outputs, and what each seeded check establishes. |
| [Maintenance notes](docs/maintenance.md) | Current evidence, prioritized follow-up, and visual asset inventory. |
| [Positioning](docs/positioning.md) · [Phase 2 design](docs/phase2-optimization-spec.md) | Intended use and proposed future architecture; targets are not measured results. |

## Contributing and related projects

See [CONTRIBUTING.md](CONTRIBUTING.md) and [SECURITY.md](SECURITY.md). Use synthetic examples; keep real transcripts, local stores, credentials, and private debug exports out of commits. Licensed under [MIT](LICENSE).

Related projects: [Agent Peak Bench](https://github.com/2sao7sao/agent-peak-bench) for agent evaluation, [EvolveKB](https://github.com/2sao7sao/EvolveKB) for knowledge workflows, and [Video Analysis Skills](https://github.com/2sao7sao/video-analysis-skills) for structured video analysis. These are separate repositories, not a claim of an integrated product.
