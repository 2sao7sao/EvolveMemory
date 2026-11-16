# EvolveMemory 运行时参考

[返回 README](../README.zh-CN.md) · [English](runtime-reference.md)

以下公式与接口描述确定性原型。模块存在不等于完整宿主对话链路已经接通，也不代表真实模型收益已经测量。

## 2026-11-16 控制与 scope 实现切片

以下描述本轮**已通过本地验证的控制与 scope 实现切片**。完整 S1 宿主、真实模型调用、交付回执及并发撤销保证仍未完成。这里的范围限制用于本地原型，不等于生产认证或多租户隔离已经验证。

2026-11-16 本地结果：pytest **115 passed、72 subtests passed**；unittest **115 passed**；确定性 eval **11/11**、无失败；adaptive replay **PASS**。独立本地复核未发现本切片范围内的阻断项。结果对应本切片代码及以下测试；远端验证以关联实现 PR 的 Checks 为准，本地结果不替代远端检查。

### 一条 v2 存储与读取路径

v2 使用 normalized repository 作为唯一读写来源。`turns/ingest` 不再向 legacy session store 双写；`memory/query` 与 `prompt-context` 不隐式回退到 `/sessions` 的旧数据。已有 `/sessions` 数据保留，不删除、不自动搬迁；需要时由应用明确调用现有 `NormalizedSQLiteMemoryRepository.migrate_store(store=..., user_id=..., session_id=..., now=...)` 迁移。旧 session API 和下方独立 Python runtime 示例不具有 v2 用户设置治理，不能混用两者的控制承诺。

两条 v2 读入口共用 `prepare_v2_query`；先选择允许的 scope，再由 `apply_read_controls` 在排序、候选/debug 返回及上下文编译前过滤 key、layer、sensitive 与 profile。被禁记录不会因相关性更高而恢复。写侧也使用当前设置，临时指令、`auto_write=false` 或 master-off 不应派生新的 profile evidence。

### 字段、范围与项目开启

| 入口 / 字段 | 实现语义 |
| --- | --- |
| Ingest `session_id`, `project_id`, `domain` | 由可信宿主提供当前范围；不由 query 自行猜测授权。 |
| Ingest `memory_scope` | 可为 `turn/session/project/domain/global`；未指定时为 `session`。自然语言仅可收窄为临时 turn/session，不能扩大项目或全局分享。 |
| Query / prompt-context `session_id`, `project_id`, `domain` | session 记录按 session 与 project 精确匹配；`None` 表示未绑定值，不表示全用户搜索。 |
| Settings `enabled_project_ids` | 默认 `[]`；project scope 读写须先开启相应项目。 |
| Settings `allow_global_memory` | 默认 `false`；global scope 读写须单独开启。 |
| Domain scope | 需显式 domain；携带 project 时，该项目也须已开启。 |

项目开启后，另一个 session 可以读取同项目的 project-scope **记录**；这不等于已经实现跨线程原始会话索引或历史全文检索。不要省略 session/project 来表达“查全部”。

例如，宿主先通过 `PUT /v2/users/{user_id}/memory/settings` 保存：

```json
{"enabled_project_ids": ["project-A"], "allow_global_memory": false}
```

再为 project-A 摄取一条项目记录：

```json
{
  "session_id": "thread-A1",
  "project_id": "project-A",
  "memory_scope": "project",
  "text": "记住，回答直接一点，先给结论。"
}
```

同项目后续 query 可使用 `{"session_id":"thread-A2","project_id":"project-A","query":"在本项目中怎么回答代码 review 问题？"}`。`project-B` 或未绑定 project 不继承 A 的权限；相关度与文字中的“全局”不能打开分享范围。

### 画像确认、事件追问与复核

- 个人 inferred profile 除了通过当前设置和 scope，还必须有实际 review resolution 产生的 `metadata.user_review_approved=true`（附 `review_id` 与确认时间）。高置信、旧 `allowed_use` 或全局画像开关不代替这条确认标记；支持该画像的记录被禁用后也不能继续借画像带入内容。
- 事件追问默认逐事件关闭。通过 `PUT /v2/users/{user_id}/memory/events/{memory_id}/followup` 与 `{"enabled":true}` 为一个事件开启；`{"enabled":false}` 关闭。它受全局 `allow_event_followup` 和当前记录控制约束；全局开关打开不会批量开启事件。
- Review resolve 在批准时重新读取当前设置。候选排队后若 key/layer/sensitivity/project/global 权限被撤回，返回 **409** 并保持 **pending**，不先标 approved 再失败。
- 纠错只接受 ACTIVE 目标；删除和 forget-all 会撤销相关 pending reviews。审批再次检查 target/source 的状态、scope、设置与时间，不能用排队的旧提案恢复已删除或过期的来源。
- Profile evidence 使用真实 record ID，并与 source_turn_id 共同去重；同一合并 record 的不同源 turn 可以保留，重复源不会被当成新的证据。旧数据库及旧 evidence 唯一约束的无损迁移已有固定测试。
- 事件事实能否作为背景读取与是否允许主动追问分开判断。本轮没有实现“用户已收到追问”的交付回执、并发配额或生成途中的撤销保证。

## Mathematical Runtime

EvolveMemory 把 memory 行为设计成可打分、可解释、可评估的决策链。当前规则是确定性的，
但关键模块都会输出 factors、weights、formula、rationale 和 version，后续可以校准或用反馈数据训练。

`ScoreBreakdown` 是统一解释对象：

| Field | Example value |
| --- | --- |
| `name` | `retrieval` |
| `score` / `probability` | $0.81$ |
| `factors` | $K=0.50,\ A=0.72,\ G=0.88$ |
| `weights` | $w_K=0.22,\ w_A=0.14,\ w_G=0.06$ |
| `formula` | $S_{\mathrm{ret},v3}$ |
| `rationale` | Career query depends on current work or event state. |
| `version` | `retrieval-v3.0` |

这套数学建模按一条流水线阅读：

| 阶段 | 解决的问题 | 产物 |
| --- | --- | --- |
| Retrieval score | 候选记忆先看哪几条。 | 排序后的 candidate list。 |
| Activation | 这条记忆此刻是否仍然活跃。 | lifecycle-aware factor `A`。 |
| Semantic gravity | 词面不强但人类语境重要的记忆是否应被保留。 | impact factor `G`。 |
| Causal relevance | 这条记忆会不会改变安全或有用的回答。 | dependency factor `C`。 |
| Use gate | 排序后的记忆可以如何影响 prompt。 | direct、style、follow-up、hidden、summary、suppress。 |
| Write governance | LLM proposal 能不能成为正式记忆。 | create、review、merge、supersede、reject。 |

### 一、Retrieval Score

Retrieval 只负责候选排序，仍然不等于 permission。v2 的设置和 scope 硬过滤先于以下评分，评分只作用于仍被允许的候选。

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

所有因子都归一到 `0..1`，权重和为 `1.00`。这个分数只回答一个问题：
**哪些候选记忆应该优先被检查？** 记忆能否进入回答、以什么方式进入，仍然由 memory-use gate 决定。

| Symbol | Runtime factor | 含义 |
| --- | --- | --- |
| `K` | `keyword` | 与当前 query 的词面重合。 |
| `E` | `embedding` | 用于本地测试和 demo 的确定性 embedding-like similarity。 |
| `F` | `freshness` | 记忆的新鲜度。 |
| `L` | `layer_prior` | 当前 query intent 是否需要这个 memory layer。 |
| `A` | `activation` | 基于 confidence、age、recurrence、anomaly、fatigue 的 lifecycle activation。 |
| `C` | `causal_relevance` | 这条记忆是否会改变安全或有用的回答。 |
| `G` | `semantic_gravity` | 即使词面不重合，也具有人类语境重要性。 |

Retrieval-v3 故意拆成三层：

| Layer | 设计原因 |
| --- | --- |
| Match | `keyword` 和 `embedding` 保证普通相关性仍然有效。 |
| Lifecycle | `freshness`、`layer_prior`、`activation` 防止过期或错层记忆压过当前任务。 |
| Impact | `causal_relevance` 和 `semantic_gravity` 补回词面弱但会改变回答策略的记忆。 |

### 二、Activation And Temporal Anomaly

Memory 可以被存储，但不一定应该在当前时刻影响行为。Activation 控制生命周期衰减、强化、异常放大和疲劳抑制。

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

异常分数先单独计算，再进入 activation：

```math
Z_{\mathrm{temporal}}
= 0.50D_{\mathrm{duration}}
+ 0.30R_{\mathrm{recurrence}}
+ 0.20Q_{\mathrm{severity}}.
```

这样 recency 和状态风险不会混在一起：普通偏好可以长期安静存在，反复出现的流动状态会在必要时保持可见，
用于谨慎 follow-up 或 review。

<img src="../assets/activation_model_v2.svg" alt="状态时间异常模型：TTL、复发、异常分数和阶段转移" width="100%" />

### 三、Semantic Gravity

Semantic gravity 避免重要生活/安全语境因为词面重合弱而丢失。失业、面试、考试、健康约束、
关系变化、持续情绪状态，通常比普通风格偏好更影响回答策略。

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

Semantic gravity 也不是 permission。它只保证高影响语境不会在进入 gate 之前丢失；最终是 mention、
hidden、summary 还是 suppress，仍然由 use gate 决定。

<img src="../assets/semantic_gravity_model_v2.svg" alt="语义重力模型：语境补全、社会文化重力和个体调制" width="100%" />

### 四、Causal Relevance

Causal retrieval 问的是：这条 memory 会不会改变安全或有用的回答？

```math
C(m,q)=R(m,q)
```

当前实现不是黑盒因果模型，而是可审计的规则依赖：健康/药物约束遇到喝酒问题为 `1.00`，
职业事件遇到求职问题约为 `0.90`，考试、关系、风格类 query 会按各自依赖降级。这样做的目标是先把
“会改变回答安全性或实用性”的记忆抬上来，再交给 gate 控制可见性。

例子：用户问今晚聚会能不能喝酒时，药物或过敏相关 memory 应该被召回，即使它不是最高的关键词匹配。
但召回后仍只是 candidate；memory-use gate 决定它能否、以及如何影响回答。

## Write Governance And Inference Validation

LLM output 永远不是 writer of record。模型可以提出 memory proposal，但 validation 和确定性写入治理
决定每个 candidate 是 create、reject、review、supersede，还是只 merge evidence。

<img src="../assets/write_governance_model_v2.svg" alt="写入治理模型：proposal、weighted score、hard policy 和 decision paths" width="100%" />

写入治理使用加权分数：

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

`S_write` 只是决策里的加权部分。硬策略仍然优先：settings 禁用会 reject，明确 `do_not_remember`
会 reject，restricted memory 需要 consent，低置信 sensitive memory 需要 review，冲突记录会进入
merge、supersede 或 ask-user-confirmation。

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

| Result path | 决策来源 |
| --- | --- |
| `create` | 分数过阈值，且没有 review policy 阻挡。 |
| `review` | sensitivity、restricted consent、低置信度或低 authority 需要用户确认。 |
| `merge` | 重复 memory 只追加 evidence，不创建新 record。 |
| `supersede` | 更高或同等 authority 的 candidate 可以替换 exclusive 冲突值。 |
| `reject` | settings、明确拒绝、硬置信度下限或低加权收益阻止写入。 |

## Memory-Use Gate And Prompt Safety

Gate 会把排序后的候选转换为允许的 action。

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

Gate 的核心不是再排序一次，而是把“可用性”和“可见性”分开：高分记忆也可能因为 privacy、allowed_use、
用户显式 suppression 或 sensitive policy 只能进入 `style_only`、`summarize_only`，甚至 `suppress`。

| Gate action | Prompt channel |
| --- | --- |
| `use_directly` | 只有 safe_to_mention 时才进入 direct user facts。 |
| `style_only` | 转成 style policy，不暴露原始私人证据。 |
| `follow_up` | 对已逐个开启且全局允许的事件，最多一个短 progress cue；仍受状态与冷却约束。 |
| `hidden_constraint` | 内部 policy constraint，不对用户可见。 |
| `clarify` | 使用不确定 memory 前先确认当前事实。 |
| `summarize_only` | 只作为聚合上下文，不暴露细节。 |
| `suppress` | 只保留 audit，不进入 prompt。 |

## Developer Surface

```bash
# 运行产品 replay
python -m memory_system.demo

# 运行原始抽取 demo
python demo.py

# 启动 API
uvicorn app:app --reload

# 使用 SQLite 持久化
AME_STORAGE_BACKEND=sqlite uvicorn app:app --reload
```

独立 session runtime 示例（不是 v2 用户设置治理入口，也不会自动应用 v2 项目授权）：

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

| Endpoint | 作用 |
| --- | --- |
| `POST /v2/users/{user_id}/turns/ingest` | 摄取用户 turn 或 provider-free LLM proposal payload。 |
| `POST /v2/users/{user_id}/memory/query` | 为当前 query 检索、打分并 gate memories。 |
| `POST /v2/users/{user_id}/prompt-context` | 编译 model-ready memory context。 |
| `GET /v2/users/{user_id}/memory/review-queue` | 查看需要确认的 memories。 |
| `POST /v2/users/{user_id}/memory/review-queue/{review_id}/resolve` | 按当前设置批准/拒绝；撤权时返回 409 并保留 pending。 |
| `PUT /v2/users/{user_id}/memory/settings` | 设置主开关、项目/global 开启及 key/layer/feature 控制。 |
| `PUT /v2/users/{user_id}/memory/events/{memory_id}/followup` | 用 `{"enabled": true/false}` 单独开启或关闭事件追问。 |
| `POST /v2/users/{user_id}/memory/{memory_id}/correct` | 纠正并退休冲突 records。 |
| `POST /v2/users/{user_id}/memory/forget-all` | 带 audit trail 清空 memory。 |
| `GET /v2/users/{user_id}/memory/audit/export` | 导出 records、settings、events 和 audit data。 |
