# Live project-continuation evaluation — 2026-11-16

**Project facts can now be resumed, but preference correction failed.** This is a synthetic-user / real-model trial, not the owner's actual conversation, a blind study, or acceptance of long-term understanding. Implementation: [draft PR #17](https://github.com/2sao7sao/EvolveMemory/pull/17); protocol: [draft PR #12](https://github.com/2sao7sao/EvolveMemory/pull/12); follow-up: [issue #14](https://github.com/2sao7sao/EvolveMemory/issues/14).

## Fixed method and provenance

- [24-turn fixture](../examples/scenarios/project_continuation_zh.json), three sessions, simulated days 0/1/3. Both arms receive the same scripted user turns and only their own last two user/assistant pairs. Session changes clear recent history.
- The memory arm additionally uses real extraction, governed writes, a model selector over at most 50 already-governed candidates, final prompt compilation, and actual DeepSeek answers. The comparison arm uses recent conversation only. Both use `deepseek-flash`, answer temperature 0.2 and max output 1,400 tokens.
- No manually seeded memories, expected answers, rubric, audit export, or complete chat history are passed to the model. Model-generated answers are retained verbatim, including failures. Changes between runs affect several pipeline components: these are seen-case regressions, not an isolated causal or held-out generalization test.
- The runner records exact outgoing request bodies, actual responses, source turns, per-turn decisions, start-of-run code hashes, usage, and error status. It does not save credentials or hidden reasoning. Raw synthetic runs remain local in the maintenance workspace `reports/EvolveMemory-live-validation/`; the excerpts below are repository-hosted, the full logs are not.
- Fixture SHA-256: `413cfbd9e58c9869f6c3f70fdd57023fec943cf11ce7111e54afa18593679ac6`. Frozen [rubric](live-evaluation-rubric.md) SHA-256: `3a021bfaad7c62dd0972b1db646e1c8d56fd8ffbd684ee2ce9a212092f2f25fb`.

## Every run, including failures

| Run | Code | Actual result | Calls | Conservative cost estimate |
| --- | --- | --- | --- | --- |
| 01 | setup attempt | Local API health check failed; no provider calls | 0 | $0 |
| 02 | `eb6dbf0` | 48 answers; T24 old decision not recovered; T21 source misattribution | 72 | $0.071269 |
| 03 | `91be873` | 48 answers; T24 old decision recovered; state/retention failures remain; later source-projection review found a defect | 96 | $0.099384 |
| 04 | `a1d94e34123024d41f2c5c677bcd4abda1ca08cc` | 48 answers; final provider-projection version; T24 recovery and T19 scope correct, but wrong profile formed at T13 | 96 | $0.093850 |

Run 04 completed from 2026-11-17 01:32:26 to 01:35:18 UTC (2026-11-16 local date), about 172 seconds: **235,825 prompt tokens, 19,252 completion tokens, 96 successful calls, all `finish_reason=stop`, no errors**. Total observed successful-call estimate across runs: **$0.264503**. Estimates use peak/cache-miss rates from [DeepSeek pricing](https://api-docs.deepseek.com/quick_start/pricing/); they are not an account bill or hard billing guarantee. All calls returned the alias `deepseek-flash`; a specific underlying revision is not asserted from that alias.

## Observed outcomes in the final run

| Requested behavior | Result and boundary |
| --- | --- |
| Resume an old project decision | T24 recovers A / local SQLite, single-maintainer reproducible/debuggable loop, external authorization/sync burden and deferred integration/sharing. Actual source notes include T02/T03. T22/T23 recent pairs contain only copy-edit requests, so they do not provide the old answer. Recent-only arm cannot recover it. |
| Accept a project-scope correction | T12 changes the trial to the owner alone; T19 correctly says only the owner, with T12 delivered. Recent-only arm lacks the participant list. |
| Change with current availability | Answers adjust to the current user message, but T04/T08/T09 `current_bandwidth` proposals use prose rather than busy/available and are rejected. Typed persistent-state updating is **not demonstrated**. |
| Accept a preference correction | **Failed internally.** T13 says the correction is understood, but extracts the explicit rejection of a blanket-short-answer preference as `detail_preference=concise`, `user_implicit`. It adds positive evidence to the old preference. |
| Infer a useful profile | **Wrong inference observed.** T13 creates active `detail_tolerance=low` and `cognitive_load_preference=low_load` from T08/T11 one-off instructions plus the T13 correction. Counter-evidence weight is zero. The wrong `detail_tolerance` subsequently appears in actual answer inputs at T16/T17/T20/T22/T23; `low_load` appears at T17/T18/T19. Independent turn IDs do not establish correct interpretation or stable preference. |
| Keep one-off instructions temporary | Partial validation only: T10's turn-only detail instruction is rejected, but T08/T11 short-format requests and T10's example request are also generalized into lasting preference signals. |
| Avoid repeated reminders and confirmation | T22/T23 stay one sentence; no unrelated camera anecdote is resurfaced. The camera was never stored, so this does not validate retrieval-time event suppression. T21 still has imperfect source explanation; naturalness and correction effort require owner feedback. |

## Actual dialogue excerpts (Chinese, unedited)

### T24: old decision recovery

**Synthetic user:**

这个试点继续往下做。最早比较两条启动路线时，我最后选了哪条？当时主要考虑什么，又把哪些内容放到后面？先核对已经作出的决定，再给一个下一步；如果依据找不到就直说，不要现在重新替我选择。

**Memory-enabled DeepSeek:**

**已作出的决定：选了路线 A**——先用本地 SQLite 做单机版，把导入、查找、纠错串起来；不先做外部服务接入和多人共享。

**当时的考虑**：试点只有你一人维护，希望先拿到能独自复现、出错也容易定位的“导入—检索—纠错”闭环，不想第一周就同时承担外部授权和同步的维护负担。

**放到后面的**：外部服务接入和多人共享。外部接入等闭环跑稳后再做，第一周不做；第一轮试点也只由你本人试用，原先提到的两位协作者等下一轮再考虑。

**下一步**：按“导入—检索—纠错”拆第一周验收，先确认导入这一环能由你独立跑通并复现结果。

**Recent-only DeepSeek:**

我这边没有当时比较两条启动路线的记录，也没有你最终选了哪条、主要考虑什么、哪些内容放到后面的依据，所以没法核对这个决定。先不重新替你选。

下一步：把当时那两条路线的名称或要点发我，我据此核对已定事项和延后内容，再给推进动作。

### T13: surface agreement hides a wrong update

**Synthetic user:**

也纠正一下可能从前几轮得出的印象：我不是一概觉得越短越好，之前有几次只是忙。在项目评审里，我更喜欢先有结论，再看到主要风险和下一步；需要理解原理时，必要解释不要省。照这个方式继续，不用再逐项问我是否确认某个画像。

**Memory-enabled DeepSeek:**

明白，按这个来：评审先给结论，再列主要风险和下一步；涉及原理时该讲的讲清楚，不为了短而省。之前几次偏短是当时忙，不作为默认风格。后续不再逐项确认画像。

The actual extractor nevertheless produced `key=detail_preference`, `value=concise`, `authority=user_implicit`, with evidence “我不是一概觉得越短越好，之前有几次只是忙”. Ingest recorded `add_evidence_only` and promoted two incorrect profiles. The user's correction is not positive support for the old blanket preference. Passing schema checks and sufficient turn count did not prevent this semantic error.

## Implementation checks and next work

Final code passed **205 pytest tests + 165 subtests**, **205 unittest tests**, **11 deterministic suites**, and the existing adaptive replay. [CI for the live-tested code passed](https://github.com/2sao7sao/EvolveMemory/actions/runs/43996663764). Those checks validate contracts, not this failed inference.

1. P0: represent denial/correction as counter-evidence or a scoped replacement; prevent a negated preference from reinforcing itself. Verify the persisted record, inferred profile and later actual model input, not only the immediate acknowledgement.
2. P0: distinguish a current task instruction from stable or context-bound preference evidence; temporary short answers must not accumulate into a global tendency.
3. P1: align real extraction with the typed state contract; verify busy → available and expiry across sessions.
4. Then use unseen project scripts, repeated samples and owner feedback to evaluate naturalness, redundant questions and repeated anecdotes. Keep ordinary supported adaptation autonomous; do not fix these errors by requiring confirmation of every profile.

PR #17 remains draft because these experience failures are material. The broader protocol still lacks complete current-materials-only host controls, full source-history search, atomic concurrent revocation, delivery receipts, production authentication and longitudinal validation. This experiment neither closes #14 nor marks U01–U08 accepted.
