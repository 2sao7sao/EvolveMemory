# EvolveMemory maintenance status

Review date: **2026-11-16**. Original maintenance baseline: [`c628f00`](https://github.com/2sao7sao/EvolveMemory/commit/c628f00eb0ae5d03fee2e6d5e4208265be115a7d). PR #13 has since merged into `main@3aa4285`. This record preserves that round's evidence separately from the new controls/scope implementation slice and its local checks. Remote validation is determined by the associated implementation PR’s Checks.

## Recommendation

**Continue maintenance.** The user has selected project-task continuation and confirmed same-project authorized reuse, confirmed-only personal-profile adaptation, per-event opt-in follow-ups, and conditional source hints. The immediate milestone is consistent controls and scope, followed by a bounded host-delivery path. A full conversation or production claim is not supported.

## Original GitHub snapshot before PR #13

| Item | Evidence |
| --- | --- |
| Default branch | `main`, latest commit on 2026-06-05; latest runtime-feature commit on 2026-06-04 (`86ae868`). |
| Open issues | None returned by the repository's open-issue search on the review date. Absence of issues does not mean absence of work. |
| Open PR | [Draft #12: multi-turn conversation-memory invocation](https://github.com/2sao7sao/EvolveMemory/pull/12), head `a46a537`. It is a documentation proposal with product defaults still open, not an implemented conversation runtime. |
| Draft CI | [2026-09-04 run](https://github.com/2sao7sao/EvolveMemory/actions/runs/33837487021) failed. Its description discloses the existing clock-dependent migration test; the baseline failure was reproduced locally in this review. |
| Default-branch CI | [2026-06-05 run](https://github.com/2sao7sao/EvolveMemory/actions/runs/27003917088) succeeded at that time. It is not proof the unchanged tests still pass today. |
| Product page | [2026-06-04 Pages deployment](https://github.com/2sao7sao/EvolveMemory/actions/runs/26938850244) failed at `actions/configure-pages@v5`; upload and deployment steps were skipped. The repository Pages API returned HTTP 404 on 2026-11-16, confirming there is no configured Pages site. The optional deployment workflow is now manual-only until Pages is configured; code CI remains automatic. |

## Completed PR #13 maintenance change

### Existing behavior repaired

1. **v2 read opt-out:** after a synthetic preference was written, setting `memory_enabled=false` previously left it in both `/v2/users/{user_id}/memory/query` and `/v2/users/{user_id}/prompt-context`. Both routes now check the persisted setting before loading session memory or normalized records, then build an empty-memory response when disabled. The disabled query advertises no retrieval modes. Stored data is preserved, and re-enabling restores the prior behavior.
2. **Migration time:** `migrate_store` now accepts an optional `now` parameter and passes it to the existing active-memory filter. Existing callers still use the live clock by default. Tests supply a fixed time and separately verify that a later migration excludes the expired event while retaining the durable preference.

Scope: these changes fix the two reproduced behaviors. They do not implement PR #12, add new cross-thread access, complete fine-grained read policies, or change the legacy session-only API's settings model.

The legacy fallback mentioned in this historical section describes PR #13's baseline behavior. The newer candidate below removes implicit v2 fallback and dual-writing entirely; it does not delete the old `/sessions` store or extend v2 governance to that old API.

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

The maintenance PR CI passed on 2026-11-16 at `68d12e2`: [hosted CI](https://github.com/2sao7sao/EvolveMemory/actions/runs/43888749021). This does not rerun or approve the separate draft PR #12.

## Current controls/scope slice — local checks passed

The following implementation passed the local checks below. Independent local review found no blocker within this slice. None of PR #13's earlier counts are reused as this slice's validation; hosted CI must be read from the associated implementation PR.

| Area | Implemented behavior | Local evidence and boundary |
| --- | --- | --- |
| v2 storage | Normalized-only reads/writes; no implicit legacy session fallback or dual-write. Existing `/sessions` data remains and can be explicitly migrated with `migrate_store`. | Isolation plus existing explicit-migration tests; no claims of v2 governance on the old session API. |
| Shared read controls | Both v2 context endpoints use `prepare_v2_query` and `apply_read_controls` before scoring/debug output. Keys, layers, sensitivity, and unconfirmed profiles are filtered. | Query/prompt pairs and excluded-content assertions in `tests/test_v2_controls.py`. |
| Scope persistence and selection | Ingest adds `project_id`, `domain`, `memory_scope`; query adds `project_id`, `domain`. Session/project values match exactly, including `None` as unbound. | Save/reload/adapter, same-project record reuse, cross-project exclusion, and no omitted-identifier expansion cases. |
| Explicit sharing | `enabled_project_ids=[]` and `allow_global_memory=false` by default. Project/global reads and writes require enablement; language can narrow temporary scope only. | Disabled/enabled pairs, revocation, and temporary-language tests. |
| Profile and temporary-write controls | Profiles need an actual review marker; temporary instructions, `auto_write=false`, and master-off do not derive profile evidence. | Marker, disabled/expired source, and no-derived-write cases. |
| Event follow-up | `PUT /v2/users/{user_id}/memory/events/{memory_id}/followup` with `{enabled}` controls one event, off by default and constrained by global settings. | Per-event/global/scope control cases; no user-delivery receipt or concurrent quota proof. |
| Review and lifecycle | Approval rechecks current target/source state, scope, settings, and time; withdrawal returns 409/pending. Correction is ACTIVE-only; delete/forget-all cancel related pending reviews. | Inactive/missing targets, deleted/expired sources, scope opt-out, and pending-cancellation cases. |
| Evidence identity and schema | Profile evidence uses real record IDs plus source_turn_id deduplication. Existing rows survive old-schema migrations. | Record/evidence schema preservation, repeat migration, distinct-turn, and duplicate-source cases in `tests/test_scope_persistence.py`. |

Small-scale reuse of project-scoped records is not a complete cross-thread source-history system. This slice does not implement complete S1, real-model calls, user-delivery receipts, or concurrent-revocation guarantees. The prototype trusts host identity/context; this review does not establish production authentication or tenant isolation.

### Slice local validation

Verified locally on 2026-11-16 against this implementation slice, based on `main@3aa4285`:

| Command | Result | What it establishes |
| --- | --- | --- |
| `python3 -m pytest -q` | **115 passed, 72 subtests passed** | The repository's current local test cases; subtests are not 72 additional test methods. |
| `python3 -m unittest discover -s tests -p 'test_*.py'` | **115 passed** | Same suite through the CI-style runner. |
| `python3 -m evals.runner --suite all` | **11/11 suites**, `failures=[]` | Deterministic seed evaluations, no provider call. |
| `python3 examples/replay_adaptive_memory.py` | **PASS** | Existing standalone runtime replay, not a v2 host conversation or real-model acceptance. |

Evidence was captured in `reports/EvolveMemory-controls-validation/` in the maintenance workspace: `summary.json`, `pytest.log`, `unittest.log`, `evals.json`, and `replay.log`. The test files in this change provide reproducible cases; the external workspace logs are not an in-repository hosted artifact.

These results apply to this slice’s code and reproducible tests; remote Checks and merge status belong to the associated implementation PR. Local results do not complete S0-c, concurrent revocation, full dependency invalidation, S1 multi-turn delivery, or real-provider validation. The concrete interface is documented in [English](runtime-reference.md) and [Chinese](runtime-reference.zh-CN.md).

## Next milestones

| Priority | Work | Acceptance / blocker |
| --- | --- | --- |
| P0 | Keep the controls/scope slice and its regressions passing | Local checks pass; remote Checks must verify the associated implementation revision. |
| P1 | Update PR #12 to the confirmed product choices and current baseline | Keep protocol requirements, implemented candidate behavior, and validation results separate. |
| P1 | Add the minimal host and capture actual delivery input | A deterministic callable receives only permitted context; compiling a prompt alone is not delivery or a real-model result. |
| P1 | Complete the bounded project-task conversation slice | Recover old decisions with sources, apply current-turn overrides, and handle stale events through one host interface. |
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

## Tracked follow-up

[Next milestone / 下一阶段任务 #14](https://github.com/2sao7sao/EvolveMemory/issues/14) contains the actionable checklist. The maintenance PR [hosted CI](https://github.com/2sao7sao/EvolveMemory/actions/runs/43888749021) passed on 2026-11-16 at `68d12e2`; historical runtime and provider results retain their original scope.
