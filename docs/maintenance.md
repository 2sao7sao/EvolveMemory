# EvolveMemory maintenance status

Review date: **2026-11-16**. Baseline: [`c628f00`](https://github.com/2sao7sao/EvolveMemory/commit/c628f00eb0ae5d03fee2e6d5e4208265be115a7d). This record separates the observed remote state from checks of this maintenance change.

## Recommendation

**Continue maintenance.** There is a working deterministic prototype and an unresolved conversation-design draft. The immediate milestone is correctness of existing controls and a complete, bounded single-thread conversation path. Archiving now would abandon known unfinished work; a full production claim is not supported either.

## Observed GitHub state

| Item | Evidence |
| --- | --- |
| Default branch | `main`, latest commit on 2026-06-05; latest runtime-feature commit on 2026-06-04 (`86ae868`). |
| Open issues | None returned by the repository's open-issue search on the review date. Absence of issues does not mean absence of work. |
| Open PR | [Draft #12: multi-turn conversation-memory invocation](https://github.com/2sao7sao/EvolveMemory/pull/12), head `a46a537`. It is a documentation proposal with product defaults still open, not an implemented conversation runtime. |
| Draft CI | [2026-09-04 run](https://github.com/2sao7sao/EvolveMemory/actions/runs/33837487021) failed. Its description discloses the existing clock-dependent migration test; the baseline failure was reproduced locally in this review. |
| Default-branch CI | [2026-06-05 run](https://github.com/2sao7sao/EvolveMemory/actions/runs/27003917088) succeeded at that time. It is not proof the unchanged tests still pass today. |
| Product page | [2026-06-04 Pages deployment](https://github.com/2sao7sao/EvolveMemory/actions/runs/26938850244) failed at `actions/configure-pages@v5`; upload and deployment steps were skipped. The repository Pages API returned HTTP 404 on 2026-11-16, confirming there is no configured Pages site. The optional deployment workflow is now manual-only until Pages is configured; code CI remains automatic. |

## This maintenance change

### Existing behavior repaired

1. **v2 read opt-out:** after a synthetic preference was written, setting `memory_enabled=false` previously left it in both `/v2/users/{user_id}/memory/query` and `/v2/users/{user_id}/prompt-context`. Both routes now check the persisted setting before loading session memory or normalized records, then build an empty-memory response when disabled. The disabled query advertises no retrieval modes. Stored data is preserved, and re-enabling restores the prior behavior.
2. **Migration time:** `migrate_store` now accepts an optional `now` parameter and passes it to the existing active-memory filter. Existing callers still use the live clock by default. Tests supply a fixed time and separately verify that a later migration excludes the expired event while retaining the durable preference.

Scope: these changes fix the two reproduced behaviors. They do not implement PR #12, add new cross-thread access, complete fine-grained read policies, or change the legacy session-only API's settings model.

### Validation

| Check | Result | Scope |
| --- | --- | --- |
| Baseline `python3 -m pytest -q` | 69 passed, 1 failed | The April 16 event had expired before the live migration clock; one record was returned instead of two. |
| Updated `python3 -m pytest -q` | 72 passed, 2 subtests passed | Includes the two new test methods; normalized and legacy-fallback HTTP subcases are within the opt-out method. |
| `python3 -m unittest discover -s tests -p 'test_*.py'` | 72 passed | Same runner used by the current CI workflow. |
| `python3 -m evals.runner --suite all` | All 11 suites passed; `failures=[]` | Deterministic, provider-free seed cases only. |
| `python3 examples/replay_adaptive_memory.py` | `status: PASS`, gate 8/8 | Synthetic replay, not a live model conversation. |
| Documentation checks | Relative targets exist; `git diff --check` passes | Markdown links and whitespace, not a deployed page acceptance. |

The HTTP regressions use FastAPI TestClient. They first verify that default-enabled reads return a preference, then exercise disabling and re-enabling against normalized storage and the legacy-session fallback. They inspect candidate lists, gate output, all compiled memory sections, and the assembled prompt. No model provider was called.

Remote CI for this change and PR #12 must be checked after publication; the local results above do not imply those remote runs have passed.

## Next milestones

| Priority | Work | Acceptance / blocker |
| --- | --- | --- |
| P0 | Carry the read opt-out and deterministic migration fixes onto the maintained branch | CI passes on the exact published revision; preserve the pre-fix evidence. |
| P1 | Review PR #12's product defaults | Decide cross-thread scope, inferred-profile use, and visibility rules. Keep the PR draft until these are resolved. |
| P1 | Implement the first bounded conversation slice | Cover old decisions, source references, current-turn overrides, opt-out and stale-event behavior through a single host interface. Module checkmarks alone are insufficient. |
| P1 | Audit fine-grained read controls | Independently test disabled keys/layers, inferred profiles and event follow-up settings on already stored records. This review fixed the master opt-out only. |
| P2 | Restore Pages configuration | Read the failing job logs and repository Pages configuration; verify a successful deployment before advertising a live product page. |
| P2 | Replace the hash embedding substitute and connect an extraction provider | Version the dataset and provider; measure quality, latency, cost, and failures. Avoid presenting seeded replay scores as real-model gains. |
| P2 | Build governance UI and production controls | Authentication, tenant isolation, encryption, retention and deployment checks remain unverified. |

## README and asset use

The English and Chinese README now share a concise sequence: hero, one-line purpose, navigation, four badges, capabilities, quick start, workflow, reproducible example, status, documentation, and contribution links. Mathematical detail and API examples are preserved in [English](runtime-reference.md) and [Chinese](runtime-reference.zh-CN.md) references.

| Asset | Role |
| --- | --- |
| `assets/readme-banner.png` | Shared README hero export; the adjacent SVG is the editable source. |
| `assets/runtime_contract_map_v2.svg` | One workflow illustration in both READMEs. |
| `activation_model_v2.svg`, `semantic_gravity_model_v2.svg`, `write_governance_model_v2.svg` | Technical illustrations retained in the runtime references. |
| `docs/assets/replay_gate_summary_v2.svg` | Existing detailed replay illustration retained on disk; no longer a second large README panel. |
| Two historical hero PNGs plus `architecture.svg`, `inference_validation_engine.svg`, `mode_matrix.svg`, `semantic_gravity_world_knowledge.svg`, `state_temporal_anomaly_model.svg` | No references found in the scanned Markdown/HTML baseline. Retained pending a complete external-consumer check; not used as current README assets. |

The baseline's two unreferenced hero PNGs total approximately 3.22 MiB. Keeping them out of the README reduces visual duplication; no source asset was deleted during this review.

## Brand assets

Both language editions use the same 1600 × 600 hero, shared seated penguin, and project-specific accent and symbol. [Asset inventory and provenance](../assets/brand/README.md). Existing technical figures remain separate from brand artwork.
