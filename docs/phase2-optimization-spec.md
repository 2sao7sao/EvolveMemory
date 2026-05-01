# EvolveMemory Phase 2 Optimization Spec

**Document version:** v1.0  
**Target project:** `2sao7sao/EvolveMemory`  
**Recommended repository path:** `docs/phase2-optimization-spec.md`  
**Date:** 2026-05-01  
**Status:** Draft for Phase 2 development  
**Primary goal:** 将 EvolveMemory 从规则型 memory prototype 升级为可评测、可扩展、可治理、可集成的个人 AI memory runtime。

---

## 0. Executive Summary

EvolveMemory 当前已经具备一个很好的 Phase 1 骨架：

- 有结构化 memory schema。
- 有 slot registry。
- 有 write evaluator。
- 有 local JSON / SQLite persistence。
- 有 retrieval。
- 有 `MemoryUseGate`。
- 有 `ResponsePolicyEngine`。
- 有 prompt context builder。
- 有 FastAPI service。
- 有 correction / retirement / audit。
- 有 unit tests。

这说明项目已经不是单纯的“把聊天记录塞进向量库”的简单 memory demo，而是开始处理更关键的问题：

> 当前任务中，哪些 memory 应该被使用？以什么方式使用？哪些 memory 应该只影响风格？哪些 memory 应该被抑制？

Phase 2 的主要方向不是简单加 embedding，而是把项目升级成一个完整的 **Memory Runtime**：

```text
observe
  -> propose
  -> validate
  -> normalize
  -> score
  -> write / reject / review
  -> retrieve
  -> gate
  -> compile response policy
  -> audit
  -> evaluate
  -> improve
```

Phase 2 应该重点解决 7 个问题：

1. **Extraction 从规则升级到 LLM + schema validation + deterministic post-processing。**
2. **Retrieval 从 keyword/rule 升级到 hybrid retrieval：keyword + embedding + temporal + graph + rerank。**
3. **Memory item 从 flat record 升级到 canonical memory + evidence + audit + operation log。**
4. **Event memory 从 label 升级到 event state machine。**
5. **Memory gate 从 hardcoded rules 升级到 policy-configurable gate。**
6. **Persistence 从 session payload 升级到 normalized storage。**
7. **项目从 demo tests 升级到 memory quality eval harness。**

本 spec 的目标是给出一份可直接指导 Phase 2 开发的技术与产品规格。

---

## 1. Current Completion Assessment

### 1.1 Overall Completion

| Area | Current Completion | Assessment |
|---|---:|---|
| Product idea | 80% | 方向明确：memory 不只是存储，而是影响回答行为。 |
| Prototype implementation | 65–70% | 已经有 FastAPI、schema、registry、store、gating、prompt context、tests。 |
| Memory intelligence | 45–55% | 规则逻辑较清楚，但 extraction、retrieval、event、profile、decay 还浅。 |
| Production readiness | 25–35% | 缺 auth、multi-tenant、migration、encryption、UI、eval、CI、release。 |
| Open-source maturity | 20–30% | 目前更像早期研究 / design prototype。 |

### 1.2 Current Strengths

EvolveMemory 当前最值得保留和加强的能力是：

#### 1.2.1 Memory Use Gate

当前项目已经明确区分：

- `use_directly`
- `style_only`
- `follow_up`
- `suppress`

这是项目最有差异化的地方。很多 memory system 停留在 retrieval 阶段，而 EvolveMemory 进一步问：

```text
这条 memory 在当前回答里应该如何被使用？
```

这个思想应该成为 Phase 2 的核心定位。

#### 1.2.2 Memory Lifecycle

当前已经支持：

- write
- merge
- reject
- retire
- correct
- audit
- validity window
- exclusive group
- coexistence rule

这说明项目不是在做静态 facts database，而是在做动态 memory lifecycle。

#### 1.2.3 Response Policy

当前项目已经能把 memory 转化为 answer behavior，例如：

- tone
- detail level
- structure
- decision mode
- pace
- empathy level
- follow-up style

这非常重要。个人 AI 的 memory 价值不只是“我知道你是谁”，而是“我知道该如何更适合你地回答”。

#### 1.2.4 Clean Module Boundary

当前代码结构相对清楚：

```text
memory_system/
  schema.py
  registry.py
  engine.py
  gating.py
  persistence.py
  prompting.py
  service.py
  structured.py
app.py
demo.py
tests/
```

Phase 2 不应该推倒重来，而应该在这个结构上做模块化扩展。

---

## 2. Current Gaps

### 2.1 Extraction Gap

当前 raw dialogue extractor 是规则型、中文关键词优先。它适合 demo，但不能覆盖真实对话。

真实对话中需要处理：

- 否定句：`我不是单身`。
- 修正句：`刚才说错了，我现在不是在找工作`。
- 跨轮指代：`那个已经结束了`。
- 弱信号：`最近可能会考虑换工作`。
- 反讽和情绪表达。
- 多主体混淆：`我朋友失业了` 不应该写成用户失业。
- 时间表达：`去年在上海，现在回北京了`。
- 隐私偏好：`这个别记`。
- 显式记忆指令：`记住我喜欢先给结论`。

### 2.2 Retrieval Gap

当前 retrieval 主要是 keyword/rule weighted。问题是：

- 语义召回弱。
- 多语言弱。
- 同义表达弱。
- 长尾 query 弱。
- 无 graph expansion。
- 无 reranker。
- 无 memory usefulness feedback。

Phase 2 应该变成 hybrid retrieval。

### 2.3 Event Gap

当前 event memory 更接近 event label：

```text
life_event = prepare_interview
```

但真实 event 应该是状态机：

```text
prepare_interview
  status: open / progressing / blocked / resolved / stale
  stage: resume / first_round / second_round / offer / rejected
  expected_next_signal: interview date, role, result, blocker
  followup_policy: cooldown, max followups, cue intent
```

### 2.4 Profile Gap

当前 profile dimensions 比较窄：

- structure preference
- directness preference
- detail tolerance
- emotional support need
- pace preference

Phase 2 需要：

- evidence accumulation
- confidence update
- contradiction handling
- user-visible explanation
- domain-specific profile
- profile decay
- style-only enforcement

### 2.5 Storage Gap

当前 SQLite persistence 是 session-level payload storage。它适合 prototype，但不适合：

- 查询某个用户所有 active memory。
- 查询某个 key 的历史版本。
- 按时间范围查 audit。
- 增量更新。
- embedding index。
- graph edges。
- migration。
- 多租户隔离。
- 删除和合规。

### 2.6 Privacy Gap

当前已有 `sensitive` tag 和 privacy factor，但还不够。

Phase 2 需要：

- 用户 memory settings。
- user consent。
- field-level sensitivity。
- sensitive memory review queue。
- allowed-use policy。
- right-to-delete。
- audit export。
- sensitive field encryption。
- prompt visibility control。

### 2.7 Evaluation Gap

当前 tests 是功能单元测试，不是 memory quality evaluation。

Phase 2 必须建立 eval harness，覆盖：

- extraction quality
- write decision quality
- retrieval quality
- gate correctness
- privacy leakage
- stale memory usage
- contradiction handling
- answer helpfulness delta

---

## 3. Phase 2 Product Positioning

### 3.1 Product Thesis

EvolveMemory 的定位应该是：

> A memory runtime that decides not only what to remember and retrieve, but how memory is allowed to influence the next answer.

中文表达：

> EvolveMemory 不只是记忆库，而是一个 memory 使用治理层。它决定哪些记忆可以被写入、哪些可以被检索、哪些可以直接影响内容、哪些只能影响风格、哪些必须被抑制。

### 3.2 Differentiation

很多 memory 项目强调：

- long-term memory
- vector retrieval
- user facts
- agent memory
- knowledge graph

EvolveMemory 应该主打：

```text
Memory Use Governance
+ Response Policy Compilation
+ Event Progress Tracking
+ User-Correctable Memory Lifecycle
```

也就是：

```text
记住什么只是第一步。
关键是：现在该不该用、怎么用、用到什么程度。
```

### 3.3 Phase 2 North Star

Phase 2 的 North Star：

> 对每次用户 query，EvolveMemory 能输出一个安全、相关、可解释、可执行的 memory context 和 response policy，使下游模型回答更个性化，但不过度暴露、不过度拟合、不过度冒犯。

---

## 4. Target Architecture

### 4.1 High-Level Architecture

```mermaid
flowchart TD
    A[User Turn] --> B[Turn Preprocessor]
    B --> C[LLM Memory Proposal Extractor]
    C --> D[Schema Validator]
    D --> E[Normalizer]
    E --> F[Sensitivity Classifier]
    F --> G[Contradiction Detector]
    G --> H[Write Evaluator]
    H --> I[Memory Operation Planner]
    I -->|write/update/merge| J[Memory Store]
    I -->|needs review| K[Review Queue]
    I -->|reject| L[Audit: Reject]
    J --> M[Embedding Index]
    J --> N[Graph Index]
    J --> O[Event State Manager]
    J --> P[Audit Log]

    Q[User Query] --> R[Query Intent Classifier]
    R --> S[Retrieval Planner]
    S --> T[Hybrid Retriever]
    T --> U[Reranker]
    U --> V[Memory Use Gate]
    V --> W[Context Compiler]
    W --> X[Response Policy]
    W --> Y[Model-Ready Memory Context]
    X --> Z[LLM / Agent]
    Y --> Z

    Z --> AA[Response]
    AA --> AB[Usage Feedback]
    AB --> P
    AB --> AC[Evaluation / Metrics]
```

### 4.2 Runtime Modes

Phase 2 should support these modes:

| Mode | Purpose | Output |
|---|---|---|
| `observe` | 读取用户 turn，识别可能有记忆价值的信息 | raw candidate signals |
| `propose` | LLM / rule extractor 提出 candidate memories | candidate memory list |
| `validate` | JSON schema + semantic validation | valid candidates |
| `score` | 计算 write score | write decisions |
| `plan` | 决定 create/update/merge/supersede/reject/review | memory operations |
| `persist` | 写入 normalized store + embedding + graph | stored memory |
| `retrieve` | 为当前 query 找候选 memory | candidate memories |
| `gate` | 决定 memory 使用方式 | gate decisions |
| `compile` | 生成 prompt-safe memory context 和 response policy | compiled context |
| `correct` | 用户纠错、删除、禁用 | correction operation |
| `audit` | 解释 memory lifecycle | audit log |
| `evaluate` | 离线或在线评测 memory quality | metrics |

---

## 5. Memory Layer Model

Phase 2 建议从当前 4 类 memory 扩展到 7 层。

```text
MemoryLayer
├── working_memory
├── semantic_fact
├── preference
├── inferred_profile
├── episodic_event
├── relationship_graph
└── procedural_memory
```

### 5.1 `working_memory`

当前 session 内的临时上下文。

Examples:

- 当前上传的文件。
- 当前任务目标。
- 当前约束：`只看这个 PDF`。
- 当前对话里的临时变量。

Rules:

- 默认短 TTL。
- 不进入 long-term memory。
- 可以直接进入 prompt。
- session 结束后可清除。

### 5.2 `semantic_fact`

用户明确陈述的事实。

Examples:

- 用户在上海。
- 用户是硕士。
- 用户正在找工作。
- 用户是产品经理。

Rules:

- 高置信才写。
- 有有效期。
- 可以被 supersede。
- query 相关才 direct use。
- sensitive fact 需要更强 relevance。

### 5.3 `preference`

用户显式服务偏好。

Examples:

- 先给结论。
- 不要太啰嗦。
- 喜欢表格。
- 少问 follow-up。
- 直接给建议。

Rules:

- 显式偏好优先。
- 多数情况下 `style_only`。
- 不应该在回答中显式提到，除非用户问“你记得我什么偏好吗”。

### 5.4 `inferred_profile`

系统根据多次交互推断出的用户画像。

Examples:

- 用户偏好直接回答。
- 用户 detail tolerance 较低。
- 用户在技术问题上喜欢深入解释。
- 用户在生活建议上更需要情绪支持。

Rules:

- 不能当作硬事实。
- 默认 `style_only`。
- 必须有 evidence accumulation。
- 必须可被用户查看和纠正。
- 单次弱信号不能形成强 profile。

### 5.5 `episodic_event`

有时间、阶段、进展的事件。

Examples:

- 准备面试。
- 正在找工作。
- 搬家。
- 分手。
- 准备考试。
- 做一个项目。

Rules:

- 有 event status。
- 有 expected next signal。
- 有 follow-up cooldown。
- 事件结束后可转成 residue facts。
- sensitive event 默认 stricter gate。

### 5.6 `relationship_graph`

实体和实体之间的关系。

Examples:

- 用户参与项目 A。
- 项目 A 依赖 API B。
- Alice 是用户同事。
- 用户住在城市 C。

Rules:

- graph edge 有时间有效期。
- edge 有 confidence 和 evidence。
- edge 可 invalidated。
- retrieval 可做 graph expansion。

### 5.7 `procedural_memory`

用户和 agent 共同形成的工作流程、协作偏好、长期任务方式。

Examples:

- 代码审查时先列风险，再给 patch。
- 写产品 spec 时先给 PRD，再给任务拆分。
- 用户喜欢先看可执行 checklist。
- 用户不喜欢泛泛建议。

Rules:

- 高价值。
- 高复用。
- 多数进入 response policy。
- 不一定显式输出。

---

## 6. Core Data Model

### 6.1 `MemoryRecord`

```python
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID
from pydantic import BaseModel, Field


MemoryLayer = Literal[
    "working_memory",
    "semantic_fact",
    "preference",
    "inferred_profile",
    "episodic_event",
    "relationship_graph",
    "procedural_memory",
]

MemoryStatus = Literal[
    "candidate",
    "active",
    "stale",
    "superseded",
    "rejected",
    "deleted",
]

Authority = Literal[
    "user_explicit",
    "user_implicit",
    "assistant_inferred",
    "external_source",
    "system",
]

Sensitivity = Literal[
    "public",
    "personal",
    "sensitive",
    "restricted",
]

AllowedUse = Literal[
    "direct",
    "style",
    "follow_up",
    "hidden_constraint",
    "analytics",
    "never_prompt",
]


class MemoryRecord(BaseModel):
    id: UUID
    tenant_id: str
    user_id: str
    session_id: str | None = None

    layer: MemoryLayer
    key: str
    value: Any
    normalized_value: Any | None = None

    confidence: float = Field(ge=0.0, le=1.0)
    authority: Authority
    sensitivity: Sensitivity = "personal"
    allowed_use: list[AllowedUse] = Field(default_factory=list)

    evidence_ids: list[UUID] = Field(default_factory=list)
    source_turn_ids: list[str] = Field(default_factory=list)
    source_text_hash: str | None = None

    valid_from: datetime
    valid_to: datetime | None = None
    observed_at: datetime
    last_confirmed_at: datetime | None = None
    last_used_at: datetime | None = None

    status: MemoryStatus = "active"
    version: int = 1
    supersedes: UUID | None = None
    superseded_by: UUID | None = None

    exclusive_group: str | None = None
    coexistence_rule: Literal[
        "coexist",
        "mutually_exclusive",
        "conditionally_exclusive",
        "mergeable",
    ] = "coexist"

    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
```

### 6.2 `MemoryEvidence`

```python
class MemoryEvidence(BaseModel):
    id: UUID
    tenant_id: str
    user_id: str
    memory_id: UUID | None = None

    turn_id: str
    role: Literal["user", "assistant", "tool", "external"]
    quote: str
    quote_hash: str

    extraction_rationale: str
    extractor_version: str
    confidence: float = Field(ge=0.0, le=1.0)

    created_at: datetime
```

### 6.3 `MemoryOperation`

```python
MemoryOperationType = Literal[
    "create",
    "merge",
    "update",
    "supersede",
    "retire",
    "reject",
    "ask_user_confirmation",
    "add_evidence_only",
]


class MemoryOperation(BaseModel):
    operation: MemoryOperationType
    candidate: MemoryRecord
    target_memory_id: UUID | None = None
    reason: str
    score: float
    requires_user_review: bool = False
    audit_metadata: dict[str, Any] = Field(default_factory=dict)
```

### 6.4 `MemoryAuditEvent`

```python
class MemoryAuditEvent(BaseModel):
    id: UUID
    tenant_id: str
    user_id: str
    actor: Literal["system", "user", "admin", "extractor", "consolidator"]
    action: Literal[
        "proposed",
        "created",
        "merged",
        "updated",
        "superseded",
        "retired",
        "deleted",
        "rejected",
        "used",
        "suppressed",
        "review_requested",
        "review_approved",
        "review_denied",
    ]
    memory_id: UUID | None
    before: dict[str, Any] | None = None
    after: dict[str, Any] | None = None
    reason: str
    policy_version: str
    created_at: datetime
```

### 6.5 `EventMemoryState`

```python
class FollowupPolicy(BaseModel):
    enabled: bool = True
    cue_intents: list[str] = Field(default_factory=list)
    cooldown_days: int = 7
    max_followups_per_event: int = 3
    last_followed_up_at: datetime | None = None
    followup_count: int = 0
    user_rejected_followup: bool = False


class EventMemoryState(BaseModel):
    memory_id: UUID
    event_type: str
    status: Literal["open", "progressing", "blocked", "resolved", "stale", "abandoned"]
    stage: str
    expected_next_signals: list[str] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)
    related_state_keys: list[str] = Field(default_factory=list)
    followup_policy: FollowupPolicy
    resolution_summary: str | None = None
    updated_at: datetime
```

### 6.6 `MemoryGraphEdge`

```python
class MemoryGraphEdge(BaseModel):
    id: UUID
    tenant_id: str
    user_id: str
    subject_id: UUID
    predicate: str
    object_id: UUID
    confidence: float = Field(ge=0.0, le=1.0)
    valid_from: datetime
    valid_to: datetime | None = None
    evidence_ids: list[UUID] = Field(default_factory=list)
    status: Literal["active", "invalidated", "deleted"] = "active"
    created_at: datetime
    updated_at: datetime
```

---

## 7. Slot Registry v2

### 7.1 Purpose

`MemorySlotRegistry` 不应该只是默认 key 列表。Phase 2 中它应该变成 memory system 的 declarative policy registry。

每个 slot 应定义：

- layer
- key
- value schema
- sensitivity
- default TTL
- allowed use
- write threshold
- merge strategy
- conflict strategy
- decay strategy
- review requirement
- prompt visibility

### 7.2 Slot Definition

```python
class SlotDefinition(BaseModel):
    key: str
    layer: MemoryLayer
    description: str
    examples: list[str] = Field(default_factory=list)

    value_schema: dict[str, Any] = Field(default_factory=dict)
    sensitivity: Sensitivity = "personal"
    allowed_use: list[AllowedUse] = Field(default_factory=list)

    default_valid_days: int | None = None
    dynamics: Literal["static", "semi_static", "fluid", "procedural", "event"]

    coexistence_rule: Literal[
        "coexist",
        "mutually_exclusive",
        "conditionally_exclusive",
        "mergeable",
    ] = "coexist"
    exclusive_group: str | None = None

    write_threshold: float = 0.55
    review_required: bool = False
    user_confirmation_required: bool = False

    merge_strategy: Literal[
        "replace",
        "append_evidence",
        "max_confidence",
        "weighted_average",
        "event_update",
    ] = "append_evidence"

    decay_policy: dict[str, Any] = Field(default_factory=dict)
    gate_policy: dict[str, Any] = Field(default_factory=dict)
```

### 7.3 Example Registry YAML

```yaml
slots:
  - key: response_opening
    layer: preference
    description: User preference for answer opening.
    examples: ["先给结论", "直接说重点"]
    sensitivity: personal
    allowed_use: [style, hidden_constraint]
    dynamics: procedural
    coexistence_rule: mutually_exclusive
    exclusive_group: response_opening
    write_threshold: 0.45
    merge_strategy: replace
    gate_policy:
      default_action: style_only
      safe_to_mention: false

  - key: relationship_status
    layer: semantic_fact
    description: User-stated relationship status.
    sensitivity: sensitive
    allowed_use: [direct]
    dynamics: semi_static
    coexistence_rule: mutually_exclusive
    exclusive_group: relationship_status
    write_threshold: 0.75
    review_required: true
    gate_policy:
      default_action: suppress
      require_high_relevance: true
      safe_to_mention: true

  - key: current_emotional_state
    layer: semantic_fact
    description: Recent emotional state that can shape response style.
    sensitivity: sensitive
    allowed_use: [style, direct]
    dynamics: fluid
    default_valid_days: 14
    coexistence_rule: mutually_exclusive
    exclusive_group: current_emotional_state
    write_threshold: 0.65
    gate_policy:
      default_action: style_only
      direct_use_requires_query_intent: [mental_health, emotional_support]
```

---

## 8. Ingest Pipeline Spec

### 8.1 Pipeline

```text
raw_turn
  -> TurnPreprocessor
  -> MemoryProposalExtractor
  -> SchemaValidator
  -> Normalizer
  -> SensitivityClassifier
  -> ContradictionDetector
  -> WriteEvaluator
  -> OperationPlanner
  -> MemoryStore
  -> EmbeddingIndexer
  -> GraphIndexer
  -> EventStateManager
  -> AuditLogger
```

### 8.2 `TurnPreprocessor`

Responsibilities:

- normalize whitespace
- detect language
- assign turn id
- hash raw text
- detect explicit memory commands
- detect non-memory commands
- extract coarse time expressions

Example output:

```json
{
  "turn_id": "turn_20260501_0001",
  "language": "zh-CN",
  "text": "记住，我喜欢你先给结论，然后分步骤。",
  "memory_command": "remember",
  "timestamp": "2026-05-01T09:00:00+08:00"
}
```

### 8.3 Explicit Memory Commands

Support:

```text
remember this
记住这个
以后都这样回答
不要记这个
别记我的...
忘掉...
删除关于...的记忆
更新一下，我现在...
刚才说错了...
```

Rules:

```text
if command == remember:
    boost write score
if command == do_not_remember:
    reject memory and add user setting if applicable
if command == forget:
    retire/delete matching memory
if command == correction:
    supersede existing memory
```

---

## 9. LLM Memory Proposal Extractor

### 9.1 Goal

LLM extractor 不直接写 memory。它只提出 candidate memories。真正写入由 deterministic policy 决定。

### 9.2 Extractor Input

```json
{
  "turn": {
    "id": "turn_001",
    "role": "user",
    "text": "我最近准备面试，有点焦虑。回答直接一点，先给结论。",
    "timestamp": "2026-05-01T09:00:00+08:00"
  },
  "recent_context": [
    {"role": "user", "text": "我在找工作"}
  ],
  "active_memory_summary": [
    {"key": "work_status", "value": "job_seeking"}
  ],
  "slot_registry_subset": [
    {"key": "response_opening", "layer": "preference"}
  ]
}
```

### 9.3 Extractor Output Schema

```json
{
  "candidate_memories": [
    {
      "layer": "episodic_event",
      "key": "career_event",
      "value": {
        "event_type": "career.interview_preparation",
        "status": "open",
        "stage": "preparing"
      },
      "confidence": 0.88,
      "authority": "user_explicit",
      "sensitivity": "personal",
      "evidence": "最近准备面试",
      "reasoning": "User explicitly states they are preparing for interviews.",
      "validity": {
        "valid_from": "2026-05-01T09:00:00+08:00",
        "valid_to": null
      },
      "write_intent": "upsert",
      "possible_conflicts": []
    },
    {
      "layer": "semantic_fact",
      "key": "current_emotional_state",
      "value": "anxious",
      "confidence": 0.82,
      "authority": "user_explicit",
      "sensitivity": "sensitive",
      "evidence": "有点焦虑",
      "reasoning": "User directly describes current emotional state.",
      "validity": {
        "valid_from": "2026-05-01T09:00:00+08:00",
        "valid_to": "2026-05-15T09:00:00+08:00"
      },
      "write_intent": "upsert",
      "possible_conflicts": ["current_emotional_state"]
    },
    {
      "layer": "preference",
      "key": "communication_style",
      "value": "direct",
      "confidence": 0.93,
      "authority": "user_explicit",
      "sensitivity": "personal",
      "evidence": "回答直接一点",
      "reasoning": "User explicitly asks for direct responses.",
      "validity": {
        "valid_from": "2026-05-01T09:00:00+08:00",
        "valid_to": null
      },
      "write_intent": "upsert",
      "possible_conflicts": ["communication_style"]
    }
  ],
  "non_memories": [
    {
      "text": "最近",
      "reason": "Temporal modifier, not a standalone memory."
    }
  ]
}
```

### 9.4 Extractor Prompt Requirements

The extractor prompt must include strict instructions:

```text
You are a memory proposal extractor, not a memory writer.
Only propose memories that may improve future personalization, safety, continuity, or task performance.
Do not write facts about third parties as facts about the user.
Do not infer sensitive attributes unless explicitly stated by the user.
If the user says not to remember something, output a do_not_remember command instead of a memory.
If a statement is uncertain, lower confidence and mark authority as user_implicit or assistant_inferred.
Return JSON only.
```

### 9.5 Validation and Repair

Implementation requirements:

- Validate with Pydantic / JSON schema.
- If invalid JSON, run repair once.
- If still invalid, reject extractor result and audit.
- Never write raw LLM output directly.

---

## 10. Write Evaluator v2

### 10.1 Write Score

Replace pure multiplication with configurable weighted scoring.

```text
write_score =
  0.18 * confidence
+ 0.16 * future_reuse
+ 0.14 * personalization_gain
+ 0.12 * stability
+ 0.10 * user_authority
+ 0.10 * evidence_quality
+ 0.08 * novelty
+ 0.07 * actionability
+ 0.05 * privacy_adjustment
```

### 10.2 Factor Definitions

| Factor | Meaning |
|---|---|
| `confidence` | Extractor confidence and evidence clarity. |
| `future_reuse` | Probability this memory helps future turns. |
| `personalization_gain` | Whether it changes response behavior. |
| `stability` | Whether it remains true long enough. |
| `user_authority` | Explicit user statement > inference. |
| `evidence_quality` | Evidence is direct, unambiguous, user-owned. |
| `novelty` | Not duplicate of existing memory. |
| `actionability` | Can guide response or follow-up. |
| `privacy_adjustment` | Penalize sensitive memory unless clearly useful and allowed. |

### 10.3 Hard Rules

```python
if user_command == "do_not_remember":
    reject()

if user_command == "remember":
    boost_score(0.25)

if sensitivity == "restricted" and not user_consent:
    reject_or_review()

if confidence < 0.45:
    reject()

if confidence < 0.65 and sensitivity in {"sensitive", "restricted"}:
    review_queue()

if contradiction_detected and candidate_authority < existing_authority:
    review_queue()

if contradiction_detected and candidate_authority >= existing_authority:
    supersede()
```

### 10.4 Write Decisions

```python
class WriteDecision(BaseModel):
    candidate_id: UUID
    should_write: bool
    score: float
    threshold: float
    operation: MemoryOperationType
    reason: str
    factors: dict[str, float]
    requires_user_review: bool
```

---

## 11. Conflict and Contradiction Handling

### 11.1 Conflict Types

| Conflict Type | Example | Operation |
|---|---|---|
| exclusive slot conflict | `single` vs `dating` | supersede old active value |
| temporal conflict | `去年在上海，现在在北京` | close old valid_to, create new |
| authority conflict | inferred vs user explicit | user explicit wins |
| sensitivity conflict | memory disabled by settings | reject / delete |
| duplicate | same preference repeated | merge evidence |
| event progress | `准备面试` -> `拿到 offer` | update event status |
| correction | `刚才说错了` | supersede + audit correction |

### 11.2 Supersession Rule

Do not delete old memory by default. Use valid windows.

```text
old_memory.status = superseded
old_memory.valid_to = candidate.valid_from
candidate.supersedes = old_memory.id
candidate.status = active
```

### 11.3 Correction Rule

If user explicitly corrects memory:

```text
1. Find active memory by key / exclusive group.
2. Retire or supersede existing memory.
3. Create new memory with authority=user_explicit and confidence=1.0.
4. Add audit event action=corrected/superseded.
5. Optionally notify memory review UI.
```

---

## 12. Hybrid Retrieval Spec

### 12.1 Retrieval Pipeline

```text
query
  -> QueryIntentClassifier
  -> MemoryNeedClassifier
  -> RetrievalPlanner
  -> Candidate Retrieval
       - keyword search
       - vector search
       - slot search
       - temporal search
       - graph expansion
       - recent session recall
  -> Candidate Deduplication
  -> Reranker
  -> MemoryUseGate
```

### 12.2 Query Intent Classifier

```python
class QueryIntent(BaseModel):
    intent: str
    domain: str | None
    needs_memory: bool
    memory_sensitivity_allowed: bool
    desired_personalization_strength: Literal["none", "low", "medium", "high"]
    allowed_layers: list[MemoryLayer]
```

Example:

```json
{
  "intent": "career_advice",
  "domain": "career",
  "needs_memory": true,
  "memory_sensitivity_allowed": false,
  "desired_personalization_strength": "medium",
  "allowed_layers": ["semantic_fact", "preference", "episodic_event", "inferred_profile"]
}
```

### 12.3 Retrieval Plan

```python
class RetrievalPlan(BaseModel):
    query_intent: QueryIntent
    retrieval_modes: list[Literal["keyword", "embedding", "graph", "temporal", "slot", "recent"]]
    max_candidates: int = 40
    max_prompt_memories: int = 8
    recency_bias: float = 0.2
    include_sensitive: bool = False
    include_stale: bool = False
```

### 12.4 Retrieval Score

```text
retrieval_score =
  0.30 * semantic_similarity
+ 0.12 * keyword_match
+ 0.18 * intent_slot_match
+ 0.10 * recency_score
+ 0.10 * authority_score
+ 0.08 * graph_proximity
+ 0.07 * historical_usefulness
+ 0.05 * freshness_validity
```

### 12.5 Candidate Sources

| Source | Description |
|---|---|
| keyword | exact / BM25 match over key, value, evidence |
| embedding | semantic similarity over memory text |
| slot | direct slot match based on query intent |
| temporal | recently updated / time-sensitive states |
| graph | connected nodes and relationships |
| recent | current session / recent turns |

### 12.6 Reranker

The reranker should consider:

- query relevance
- whether memory changes answer quality
- freshness
- authority
- sensitivity
- duplication
- token cost
- current user query conflict

Output:

```python
class RankedMemoryCandidate(BaseModel):
    memory: MemoryRecord
    retrieval_score: float
    rerank_score: float
    retrieval_sources: list[str]
    rationale: list[str]
```

---

## 13. Memory Use Gate v2

### 13.1 Actions

Extend current 4 actions to 7 actions.

```text
MemoryUseAction
├── use_directly
├── style_only
├── follow_up
├── clarify
├── hidden_constraint
├── summarize_only
└── suppress
```

### 13.2 Action Definitions

| Action | Meaning | Prompt Visibility |
|---|---|---|
| `use_directly` | 可作为回答内容事实使用 | visible |
| `style_only` | 只影响语气、结构、详略 | policy_only |
| `follow_up` | 触发一次轻量进展问题 | visible or policy_only |
| `clarify` | 与当前输入冲突，需要澄清 | visible |
| `hidden_constraint` | 作为安全 / 偏好约束静默执行 | hidden |
| `summarize_only` | 只进入聚合摘要，不暴露细节 | policy_only |
| `suppress` | 不使用 | blocked |

### 13.3 Gate Decision Schema

```python
class MemoryGateDecision(BaseModel):
    memory_id: UUID
    layer: MemoryLayer
    action: Literal[
        "use_directly",
        "style_only",
        "follow_up",
        "clarify",
        "hidden_constraint",
        "summarize_only",
        "suppress",
    ]
    score: float
    factors: dict[str, float]
    rationale: list[str]
    prompt_visibility: Literal["visible", "policy_only", "hidden", "blocked"]
    safe_to_mention: bool
```

### 13.4 Gate Factors

```text
gate_score =
  0.22 * query_relevance
+ 0.14 * freshness
+ 0.14 * authority
+ 0.16 * utility
+ 0.14 * privacy_safety
+ 0.08 * user_preference_alignment
+ 0.06 * token_efficiency
+ 0.06 * contradiction_safety
```

### 13.5 Gate Rules

```python
if memory.status != "active":
    suppress()

if memory.valid_to and now > memory.valid_to:
    suppress_or_summarize_only()

if memory.sensitivity == "restricted":
    suppress_unless_explicitly_requested_and_allowed()

if memory.layer == "inferred_profile" and action == "use_directly":
    downgrade_to_style_only()

if memory.layer == "preference":
    style_only_or_hidden_constraint()

if memory.layer == "episodic_event" and event_is_active and query_is_related:
    follow_up_if_cooldown_passed()

if current_user_message_conflicts_with_memory:
    clarify_or_supersede()

if sensitive_memory_relevance < threshold:
    suppress()
```

### 13.6 Privacy Thresholds

```yaml
gate_policy:
  sensitivity_thresholds:
    public:
      direct_min_relevance: 0.30
    personal:
      direct_min_relevance: 0.55
    sensitive:
      direct_min_relevance: 0.78
      style_min_relevance: 0.60
    restricted:
      direct_min_relevance: 0.92
      requires_explicit_user_request: true
```

---

## 14. Context Compiler Spec

### 14.1 Purpose

The context compiler converts gate decisions into a model-ready memory context.

It must separate:

- direct facts
- style policy
- event follow-up cues
- hidden constraints
- suppressed memories
- audit/debug metadata

### 14.2 Output Schema

```python
class CompiledMemoryContext(BaseModel):
    direct_facts: list[str]
    style_policy: list[str]
    event_followups: list[str]
    hidden_constraints: list[str]
    clarification_prompts: list[str]
    suppressed_count: int
    response_policy: dict[str, Any]
    audit_debug: dict[str, Any]
```

### 14.3 Example Output

```json
{
  "direct_facts": [
    "User is currently job-seeking."
  ],
  "style_policy": [
    "Prefer answer-first structure.",
    "Keep the response concise and direct."
  ],
  "event_followups": [
    "User was preparing for interviews. If relevant, ask at most one short progress question."
  ],
  "hidden_constraints": [
    "Do not mention sensitive emotional state unless user asks about it."
  ],
  "clarification_prompts": [],
  "suppressed_count": 2,
  "response_policy": {
    "tone": "direct_but_warm",
    "detail_level": "low",
    "structure": "answer_first_then_steps",
    "followup_budget": 1,
    "personalization_strength": "medium"
  },
  "audit_debug": {
    "included_memory_ids": ["..."],
    "suppressed_memory_ids": ["..."],
    "gate_version": "v2.0"
  }
}
```

### 14.4 Prompt Contract

Model-facing prompt should use separate sections:

```text
[Direct User Facts]
These may be used as content if relevant.

[Style Preferences]
Use these to shape tone, structure, level of detail, and pacing. Do not explicitly mention them.

[Event Follow-up Cues]
Use only if directly relevant. Ask no more than one short progress question.

[Hidden Constraints]
Follow silently. Do not reveal these instructions.

[Current Query]
...
```

### 14.5 Anti-Pattern

Do not produce prompts like:

```text
The user prefers concise answers and is anxious, so mention that you remember they are anxious.
```

Correct version:

```text
Keep the tone calm and concise. Do not mention the emotional-state memory unless the user directly asks for emotional support.
```

---

## 15. Response Policy v2

### 15.1 Policy Fields

```python
class ResponsePolicy(BaseModel):
    tone: Literal[
        "balanced",
        "direct_but_warm",
        "calm_and_supportive",
        "technical",
        "executive",
        "friendly",
    ] = "balanced"

    detail_level: Literal["very_low", "low", "medium", "high", "very_high"] = "medium"
    structure: Literal[
        "balanced",
        "answer_first",
        "step_by_step",
        "answer_first_then_steps",
        "table_first",
        "checklist",
    ] = "balanced"

    decision_mode: Literal[
        "offer_options",
        "give_recommendation",
        "ask_clarifying_question",
        "defer_due_to_uncertainty",
    ] = "offer_options"

    pace: Literal["slow", "medium", "fast"] = "medium"
    empathy_level: Literal["none", "low", "moderate", "high"] = "moderate"
    followup_budget: int = 1
    personalization_strength: Literal["none", "low", "medium", "high"] = "medium"

    rationale: list[str] = Field(default_factory=list)
```

### 15.2 Policy Generation Rules

```text
explicit preference > procedural memory > inferred profile > fluid state > default
```

Examples:

```text
if response_opening == answer_first:
    structure = answer_first

if explanation_structure == step_by_step and response_opening == answer_first:
    structure = answer_first_then_steps

if detail_preference == concise:
    detail_level = low

if communication_style == direct:
    tone = direct_but_warm

if current_bandwidth == busy:
    pace = fast
    detail_level = min(current, low)

if current_emotional_state in [anxious, stressed] and query_intent is emotional_support:
    empathy_level = high
else:
    use hidden style constraint only
```

---

## 16. Event Skills

### 16.1 Event Skill Interface

```python
class EventSkill:
    name: str
    event_types: list[str]

    def detect(self, candidates: list[MemoryRecord]) -> list[EventMemoryState]:
        ...

    def update_state(
        self,
        event: EventMemoryState,
        new_evidence: MemoryEvidence,
    ) -> EventMemoryState:
        ...

    def expected_next_signals(self, event: EventMemoryState) -> list[str]:
        ...

    def should_follow_up(
        self,
        event: EventMemoryState,
        query: str,
        now: datetime,
    ) -> bool:
        ...

    def convert_to_residue(self, event: EventMemoryState) -> list[MemoryRecord]:
        ...
```

### 16.2 First Event Skills

| Skill | Event Types | Notes |
|---|---|---|
| `career_event_skill` | job search, interview, offer, onboarding, layoff | Highest priority for current project. |
| `learning_event_skill` | exam prep, course, skill learning, certification | Good for progress tracking. |
| `project_event_skill` | project started, blocked, shipped, changed scope | Useful for agent workflows. |
| `life_event_skill` | moving, breakup, health, relationship changes | Strict privacy gate. |

### 16.3 Career Event Skill

#### Event Types

```yaml
career_event_types:
  - career.job_search
  - career.resume_update
  - career.interview_preparation
  - career.interview_scheduled
  - career.offer_received
  - career.offer_rejected
  - career.offer_accepted
  - career.onboarding
  - career.layoff
```

#### State Transitions

```text
job_search.open
  -> interview_preparation.progressing
  -> interview_scheduled.progressing
  -> offer_received.progressing
  -> offer_accepted.resolved

interview_preparation.open
  -> blocked if user reports blocker
  -> resolved if interview done / offer accepted / user stops job search
  -> stale if no signal after TTL
```

#### Follow-Up Policy

```yaml
career.interview_preparation:
  cue_intents:
    - career_advice
    - interview_prep
    - resume
    - job_search
  cooldown_days: 7
  max_followups_per_event: 3
  question_style: one_short_question
  suppress_if_user_says:
    - 别问
    - 不想聊
    - 已经结束
    - 暂时不找了
```

#### Event-to-State Conversion

When event resolves:

```text
career.offer_accepted -> work_status = employed
career.job_search_abandoned -> work_status = unknown or not_job_seeking
interview_preparation.resolved -> retire event, keep summary if useful
```

### 16.4 Life Event Skill Privacy

Life events such as breakup, relationship, health, family, bereavement should have stricter behavior:

```text
- default action: suppress
- style-only allowed if query indicates emotional support
- direct use only if user explicitly asks or query is clearly related
- follow-up cooldown longer
- max followups lower
- review_required true
```

---

## 17. Graph Memory

### 17.1 Purpose

Graph memory helps retrieve related entities and dependencies.

Examples:

```text
User -> works_on -> Project A
Project A -> depends_on -> API B
User -> knows -> Alice
Alice -> role -> manager
User -> lives_in -> Shanghai
```

### 17.2 Node Types

```text
person
organization
project
location
skill
tool
preference
event
artifact
```

### 17.3 Edge Predicates

```text
works_on
owns
depends_on
knows
reports_to
lives_in
interested_in
learning
blocked_by
related_to
```

### 17.4 Graph Retrieval

When query mentions an entity:

```text
1. Resolve entity mention to graph node.
2. Retrieve direct node memory.
3. Expand 1-hop edges.
4. Optionally expand 2-hop if high confidence.
5. Send candidates to reranker.
```

### 17.5 Graph Safety

Do not over-expand sensitive graph edges.

```text
if edge.sensitivity == sensitive and query relevance < threshold:
    do not expand
```

---

## 18. User Memory Review and Governance

### 18.1 User Review Requirements

Users should be able to see:

- 系统记住了什么。
- 为什么记住。
- 来自哪句话。
- 什么时候记住。
- 有效期到什么时候。
- 会如何使用。
- 是否敏感。
- 是否是推断。
- 如何修改或删除。

### 18.2 API

```http
GET    /users/{user_id}/memories
GET    /users/{user_id}/memories/{memory_id}
GET    /users/{user_id}/memory-suggestions
POST   /users/{user_id}/memories/{memory_id}/approve
POST   /users/{user_id}/memories/{memory_id}/correct
POST   /users/{user_id}/memories/{memory_id}/retire
DELETE /users/{user_id}/memories/{memory_id}
GET    /users/{user_id}/memory-audit
GET    /users/{user_id}/memory-settings
POST   /users/{user_id}/memory-settings
POST   /users/{user_id}/forget-all
```

### 18.3 Memory Settings

```python
class UserMemorySettings(BaseModel):
    memory_enabled: bool = True
    allow_inferred_profile: bool = True
    allow_sensitive_memory: bool = False
    allow_event_followup: bool = True
    default_retention_days: int = 365
    disabled_keys: list[str] = Field(default_factory=list)
    disabled_layers: list[MemoryLayer] = Field(default_factory=list)
    review_required_for_sensitivity: list[Sensitivity] = Field(default_factory=lambda: ["sensitive", "restricted"])
    review_required_for_layers: list[MemoryLayer] = Field(default_factory=lambda: ["inferred_profile"])
```

### 18.4 Review Queue

```python
class MemoryReviewItem(BaseModel):
    id: UUID
    user_id: str
    candidate_memory: MemoryRecord
    reason: str
    risk_level: Literal["low", "medium", "high"]
    created_at: datetime
    expires_at: datetime | None
    status: Literal["pending", "approved", "rejected", "expired"]
```

---

## 19. Storage Spec

### 19.1 Recommended Backends

Development:

```text
SQLite + local embedding store
```

Production:

```text
PostgreSQL + pgvector
```

### 19.2 Tables

```sql
CREATE TABLE users (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  created_at TIMESTAMP NOT NULL,
  updated_at TIMESTAMP NOT NULL
);

CREATE TABLE sessions (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  user_id TEXT NOT NULL,
  created_at TIMESTAMP NOT NULL,
  updated_at TIMESTAMP NOT NULL
);

CREATE TABLE turns (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  user_id TEXT NOT NULL,
  session_id TEXT,
  role TEXT NOT NULL,
  text_hash TEXT NOT NULL,
  text_preview TEXT,
  created_at TIMESTAMP NOT NULL
);

CREATE TABLE memory_records (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  user_id TEXT NOT NULL,
  session_id TEXT,
  layer TEXT NOT NULL,
  key TEXT NOT NULL,
  value_json TEXT NOT NULL,
  normalized_value_json TEXT,
  confidence REAL NOT NULL,
  authority TEXT NOT NULL,
  sensitivity TEXT NOT NULL,
  allowed_use_json TEXT NOT NULL,
  valid_from TIMESTAMP NOT NULL,
  valid_to TIMESTAMP,
  observed_at TIMESTAMP NOT NULL,
  last_confirmed_at TIMESTAMP,
  last_used_at TIMESTAMP,
  status TEXT NOT NULL,
  version INTEGER NOT NULL,
  supersedes TEXT,
  superseded_by TEXT,
  exclusive_group TEXT,
  coexistence_rule TEXT NOT NULL,
  tags_json TEXT NOT NULL,
  metadata_json TEXT NOT NULL,
  created_at TIMESTAMP NOT NULL,
  updated_at TIMESTAMP NOT NULL
);

CREATE INDEX idx_memory_user_status ON memory_records(user_id, status);
CREATE INDEX idx_memory_user_key ON memory_records(user_id, key);
CREATE INDEX idx_memory_validity ON memory_records(user_id, valid_from, valid_to);

CREATE TABLE memory_evidence (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  user_id TEXT NOT NULL,
  memory_id TEXT,
  turn_id TEXT NOT NULL,
  role TEXT NOT NULL,
  quote_hash TEXT NOT NULL,
  quote_preview TEXT,
  extraction_rationale TEXT,
  extractor_version TEXT NOT NULL,
  confidence REAL NOT NULL,
  created_at TIMESTAMP NOT NULL
);

CREATE TABLE memory_audit_events (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  user_id TEXT NOT NULL,
  actor TEXT NOT NULL,
  action TEXT NOT NULL,
  memory_id TEXT,
  before_json TEXT,
  after_json TEXT,
  reason TEXT NOT NULL,
  policy_version TEXT NOT NULL,
  created_at TIMESTAMP NOT NULL
);

CREATE TABLE event_states (
  memory_id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  event_type TEXT NOT NULL,
  status TEXT NOT NULL,
  stage TEXT NOT NULL,
  expected_next_signals_json TEXT NOT NULL,
  blockers_json TEXT NOT NULL,
  followup_policy_json TEXT NOT NULL,
  resolution_summary TEXT,
  updated_at TIMESTAMP NOT NULL
);

CREATE TABLE memory_graph_edges (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  user_id TEXT NOT NULL,
  subject_id TEXT NOT NULL,
  predicate TEXT NOT NULL,
  object_id TEXT NOT NULL,
  confidence REAL NOT NULL,
  valid_from TIMESTAMP NOT NULL,
  valid_to TIMESTAMP,
  evidence_ids_json TEXT NOT NULL,
  status TEXT NOT NULL,
  created_at TIMESTAMP NOT NULL,
  updated_at TIMESTAMP NOT NULL
);

CREATE TABLE user_memory_settings (
  user_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  settings_json TEXT NOT NULL,
  created_at TIMESTAMP NOT NULL,
  updated_at TIMESTAMP NOT NULL
);
```

### 19.3 Embedding Table

For PostgreSQL + pgvector:

```sql
CREATE TABLE memory_embeddings (
  memory_id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  embedding_model TEXT NOT NULL,
  text_for_embedding TEXT NOT NULL,
  embedding vector(1536),
  created_at TIMESTAMP NOT NULL
);
```

For SQLite fallback, use:

- local vector index file, or
- sqlite-vss, or
- in-memory embedding index for tests.

---

## 20. API Spec v2

### 20.1 Ingest Turn

```http
POST /v2/users/{user_id}/turns/ingest
```

Request:

```json
{
  "session_id": "session_123",
  "role": "user",
  "text": "我最近准备面试，有点焦虑。回答直接一点，先给结论。",
  "timestamp": "2026-05-01T09:00:00+08:00",
  "options": {
    "extract_memory": true,
    "auto_write": true,
    "return_candidates": true
  }
}
```

Response:

```json
{
  "turn_id": "turn_001",
  "candidate_memories": [],
  "write_decisions": [],
  "operations": [],
  "active_memory_delta": {
    "created": 3,
    "updated": 0,
    "rejected": 1,
    "review_required": 0
  }
}
```

### 20.2 Query Memory Context

```http
POST /v2/users/{user_id}/memory/query
```

Request:

```json
{
  "session_id": "session_123",
  "query": "面试怎么准备？",
  "timestamp": "2026-05-01T10:00:00+08:00",
  "options": {
    "max_prompt_memories": 8,
    "include_debug": true
  }
}
```

Response:

```json
{
  "retrieval_plan": {},
  "candidates": [],
  "gate": {
    "selected": [],
    "suppressed": []
  },
  "compiled_context": {
    "direct_facts": [],
    "style_policy": [],
    "event_followups": [],
    "hidden_constraints": [],
    "response_policy": {}
  }
}
```

### 20.3 Build Prompt Context

```http
POST /v2/users/{user_id}/prompt-context
```

Response:

```json
{
  "system_guidance": "...",
  "memory_context": "...",
  "response_policy": {},
  "assembled_prompt": "..."
}
```

### 20.4 Correct Memory

```http
POST /v2/users/{user_id}/memories/{memory_id}/correct
```

Request:

```json
{
  "value": "dating",
  "evidence": "我刚才说错了，现在是恋爱中",
  "timestamp": "2026-05-01T10:00:00+08:00"
}
```

### 20.5 Retire Memory

```http
POST /v2/users/{user_id}/memories/{memory_id}/retire
```

### 20.6 Delete Memory

```http
DELETE /v2/users/{user_id}/memories/{memory_id}
```

### 20.7 Forget All

```http
POST /v2/users/{user_id}/forget-all
```

Behavior:

```text
- delete or tombstone all memory_records
- delete / invalidate embeddings
- retain minimal audit if required by product policy
- return count
```

---

## 21. Evaluation Spec

### 21.1 Why Evaluation Matters

Memory systems fail subtly. They may:

- write too much
- write wrong facts
- infer sensitive facts
- retrieve irrelevant facts
- use stale facts
- over-personalize
- mention private memory awkwardly
- fail to apply useful preferences
- repeatedly ask things the user already told it

Therefore Phase 2 must include eval from the beginning.

### 21.2 Eval Sets

| Eval Set | Purpose |
|---|---|
| `extraction_eval` | candidate memory extraction correctness |
| `write_decision_eval` | should write / should reject / review correctness |
| `retrieval_eval` | query retrieves relevant memory |
| `gate_eval` | action classification correctness |
| `contradiction_eval` | correction and supersession correctness |
| `privacy_eval` | sensitive memory suppression correctness |
| `event_eval` | event status transition correctness |
| `end_to_end_eval` | answer quality with compiled memory context |

### 21.3 Metrics

#### Extraction Metrics

```text
slot_precision
slot_recall
slot_f1
value_accuracy
sensitivity_accuracy
authority_accuracy
third_party_confusion_rate
```

#### Write Metrics

```text
write_precision
write_recall
reject_precision
review_routing_accuracy
duplicate_write_rate
wrong_memory_write_rate
```

#### Retrieval Metrics

```text
recall@k
MRR
nDCG
irrelevant_memory_rate
stale_memory_retrieval_rate
```

#### Gate Metrics

```text
direct_use_precision
style_only_accuracy
suppress_accuracy
followup_accuracy
sensitive_leakage_rate
over_personalization_rate
clarify_when_conflict_rate
```

#### Event Metrics

```text
event_detection_f1
event_status_accuracy
event_merge_accuracy
inappropriate_followup_rate
resolved_event_retirement_accuracy
```

#### End-to-End Metrics

```text
helpfulness_delta
personalization_helpfulness_delta
repeated_question_reduction
user_correction_rate
memory_deletion_rate
hallucinated_memory_rate
```

### 21.4 Golden Test Example

```json
{
  "id": "career_interview_001",
  "dialogue": [
    {"role": "user", "text": "我最近准备面试，有点焦虑。"},
    {"role": "user", "text": "回答直接一点，先给结论。"},
    {"role": "user", "text": "别记我的感情状态。"}
  ],
  "query": "面试怎么准备？",
  "expected_write": [
    {"key": "career_event", "value.event_type": "career.interview_preparation"},
    {"key": "current_emotional_state", "value": "anxious"},
    {"key": "communication_style", "value": "direct"},
    {"key": "response_opening", "value": "answer_first"}
  ],
  "expected_reject": [
    {"key": "relationship_status", "reason": "user disabled memory"}
  ],
  "expected_gate": {
    "career_event": "follow_up",
    "current_emotional_state": "style_only",
    "communication_style": "style_only",
    "response_opening": "style_only"
  }
}
```

### 21.5 Eval Runner

Command:

```bash
python -m evals.run \
  --suite extraction_eval \
  --config configs/eval.local.yaml
```

Output:

```json
{
  "suite": "extraction_eval",
  "run_id": "eval_20260501_001",
  "metrics": {
    "slot_f1": 0.84,
    "value_accuracy": 0.81,
    "sensitivity_accuracy": 0.93
  },
  "failures": [
    {
      "case_id": "privacy_007",
      "reason": "Extracted third-party fact as user fact"
    }
  ]
}
```

---

## 22. Security, Privacy, and Governance

### 22.1 Requirements

Phase 2 should support:

- tenant/user/session isolation
- API key auth
- user memory settings
- sensitive memory classification
- field-level encryption for sensitive values
- delete / forget endpoint
- audit log
- export endpoint
- no raw sensitive quote leakage in prompt
- configurable retention

### 22.2 Prompt Safety

Never expose the following unless explicitly requested and allowed:

- internal confidence scores
- hidden constraints
- memory IDs
- sensitive evidence quotes
- inferred psychological labels
- suppressed memory

### 22.3 Sensitive Memory Policy

```text
Sensitive memory can be stored only if:
  - user explicitly stated it, and
  - project settings allow sensitive memory, and
  - write score passes threshold, and
  - either review is not required or user approved it.

Sensitive memory can be used directly only if:
  - current query is strongly related, and
  - allowed_use includes direct, and
  - gate score passes sensitive threshold.
```

### 22.4 Right to Delete

Deletion behavior:

```text
- Mark memory as deleted.
- Remove from retrieval index.
- Remove / invalidate embedding.
- Remove graph edges if derived only from deleted memory.
- Keep minimal audit tombstone if needed.
```

---

## 23. Engineering Plan

### 23.1 Milestone 1: Foundation and Schema v2

Goal: prepare project for serious development.

Deliverables:

```text
- pyproject.toml
- ruff / mypy / pytest
- CI workflow
- Pydantic models for MemoryRecord / Evidence / Operation / GateDecision
- normalized SQLite repository
- migration from old session payload to v2 tables
- existing tests migrated to pytest
```

Acceptance:

```text
- all existing tests pass
- new schema unit tests pass
- old JSON/SQLite session payload can be loaded or migrated
- CI green
```

### 23.2 Milestone 2: LLM Extraction v2

Goal: replace rule-only extraction with LLM proposal extraction.

Deliverables:

```text
- LLMMemoryProposalExtractor
- extraction prompt
- JSON schema validation
- repair parser
- sensitivity classifier
- explicit memory command detector
- extraction eval set with at least 100 cases
```

Acceptance:

```text
- slot F1 >= 0.80 on eval set
- sensitivity precision >= 0.90
- invalid JSON repair success >= 0.95
- third-party confusion rate <= 3%
```

### 23.3 Milestone 3: Hybrid Retrieval and Gate v2

Goal: improve memory selection and safe use.

Deliverables:

```text
- embedding generator interface
- local vector index or pgvector support
- hybrid retriever
- query intent classifier
- retrieval planner
- reranker
- MemoryUseGate v2 with 7 actions
- context compiler v2
- retrieval/gate eval set
```

Acceptance:

```text
- retrieval recall@8 >= 0.85
- sensitive leakage rate <= 1%
- stale direct-use rate <= 3%
- gate action accuracy >= 0.80
```

### 23.4 Milestone 4: Event Skills and Graph Memory

Goal: move from facts to ongoing context.

Deliverables:

```text
- EventSkill interface
- CareerEventSkill
- LearningEventSkill
- ProjectEventSkill
- LifeEventSkill with strict privacy
- event_states table
- graph node/edge model
- graph retrieval expansion
```

Acceptance:

```text
- event detection F1 >= 0.75
- event status accuracy >= 0.75
- duplicate event merge accuracy >= 0.80
- inappropriate follow-up rate <= 5%
```

### 23.5 Milestone 5: User Review and Production Governance

Goal: make memory controllable by the user.

Deliverables:

```text
- memory review APIs
- memory settings APIs
- forget-all endpoint
- audit export
- API key auth
- tenant/user/session namespace
- sensitive field protection
```

Acceptance:

```text
- user can view active memories
- user can correct memory
- user can delete memory
- user can disable memory types
- deleted memory does not appear in retrieval or prompt context
```

---

## 24. Suggested PR Plan

### PR 1: Project Tooling

```text
- Add pyproject.toml
- Add ruff config
- Add pytest
- Add mypy optional config
- Add GitHub Actions CI
- Convert unittest to pytest or keep both temporarily
```

### PR 2: Schema v2

```text
- Add memory_system/models.py
- Add MemoryRecord
- Add MemoryEvidence
- Add MemoryOperation
- Add EventMemoryState
- Add GateDecision v2
- Keep old MemoryItem for compatibility
```

### PR 3: Repository v2

```text
- Add NormalizedSQLiteMemoryRepository
- Add tables
- Add CRUD for memory_records
- Add audit append
- Add migration utility
```

### PR 4: Extraction v2

```text
- Add LLMMemoryProposalExtractor interface
- Add RuleExtractor as fallback
- Add schema validator
- Add JSON repair
- Add explicit memory command detector
```

### PR 5: Write Evaluator v2

```text
- Add weighted scoring
- Add hard rules
- Add operation planner
- Add contradiction detector
- Add duplicate merge logic
```

### PR 6: Hybrid Retrieval

```text
- Add embedding provider interface
- Add keyword retriever
- Add vector retriever
- Add retrieval planner
- Add reranker
```

### PR 7: Gate v2

```text
- Add 7-action gate
- Add sensitivity thresholds
- Add configurable gate policy
- Add prompt visibility field
```

### PR 8: Context Compiler v2

```text
- Replace simple prompt builder with context compiler
- Add sections: direct facts, style policy, event followup, hidden constraints
- Add response policy v2
```

### PR 9: Event Skills

```text
- Add EventSkill base class
- Add CareerEventSkill
- Add event state transitions
- Add follow-up cooldown
```

### PR 10: Evaluation Harness

```text
- Add eval cases directory
- Add eval runner
- Add metrics
- Add CI optional eval smoke test
```

### PR 11: User Governance APIs

```text
- Add memory review API
- Add memory settings API
- Add forget-all API
- Add audit export API
```

### PR 12: Documentation

```text
- Add docs/architecture.md
- Add docs/memory-layers.md
- Add docs/evaluation.md
- Add docs/privacy.md
- Add docs/api.md
- Update README
```

---

## 25. File Structure Proposal

```text
EvolveMemory/
  app.py
  pyproject.toml
  README.md
  docs/
    phase2-optimization-spec.md
    architecture.md
    memory-layers.md
    api.md
    privacy.md
    evaluation.md
  memory_system/
    __init__.py
    models.py
    schema.py                  # old compatibility or deprecated
    registry.py
    settings.py
    extraction/
      __init__.py
      base.py
      rule_extractor.py
      llm_extractor.py
      prompts.py
      validator.py
      command_detector.py
    writing/
      __init__.py
      evaluator.py
      operation_planner.py
      contradiction.py
      normalizer.py
      sensitivity.py
    storage/
      __init__.py
      base.py
      sqlite_repository.py
      migrations.py
    retrieval/
      __init__.py
      intent.py
      planner.py
      keyword.py
      vector.py
      graph.py
      hybrid.py
      reranker.py
    gating/
      __init__.py
      gate.py
      policies.py
    context/
      __init__.py
      compiler.py
      response_policy.py
    events/
      __init__.py
      base.py
      career.py
      learning.py
      project.py
      life.py
    graph/
      __init__.py
      model.py
      index.py
    service.py
    api_models.py
  evals/
    cases/
      extraction_eval.jsonl
      write_decision_eval.jsonl
      retrieval_eval.jsonl
      gate_eval.jsonl
      privacy_eval.jsonl
      event_eval.jsonl
    metrics.py
    runner.py
  tests/
    test_schema_v2.py
    test_extraction.py
    test_write_evaluator.py
    test_retrieval.py
    test_gate.py
    test_context_compiler.py
    test_event_skills.py
    test_api.py
```

---

## 26. Backward Compatibility Plan

Current `MemoryItem` should not be deleted immediately.

Phase 2 should support compatibility:

```text
MemoryItem -> MemoryRecord adapter
MemoryRecord -> MemoryItem adapter for old tests if needed
```

Migration rules:

| Old Field | New Field |
|---|---|
| `memory_type=state` | `layer=semantic_fact` or `working_memory` depending on dynamics |
| `memory_type=preference` | `layer=preference` |
| `memory_type=profile` | `layer=inferred_profile` |
| `memory_type=event` | `layer=episodic_event` |
| `source` | `source_turn_ids` or metadata.source |
| `evidence` | `MemoryEvidence.quote` |
| `valid_from` | `valid_from` |
| `valid_to` | `valid_to` |
| `exclusive_group` | `exclusive_group` |
| `coexistence_rule` | `coexistence_rule` |
| `tags` | `tags` |

---

## 27. Configuration Spec

### 27.1 App Config

```yaml
app:
  environment: development
  timezone: Asia/Shanghai
  debug: true

storage:
  backend: sqlite
  sqlite_path: data/evolve_memory.sqlite3
  postgres_url: null

embedding:
  enabled: true
  provider: local
  model: text-embedding-3-small
  dimension: 1536

extraction:
  mode: hybrid
  llm_enabled: true
  rule_fallback_enabled: true
  max_repair_attempts: 1

memory:
  default_retention_days: 365
  sensitive_review_required: true
  inferred_profile_enabled: true
  event_followup_enabled: true

gate:
  policy_version: v2.0
  max_prompt_memories: 8
  sensitive_direct_min_relevance: 0.78
  restricted_direct_min_relevance: 0.92

eval:
  enabled: true
  cases_dir: evals/cases
```

---

## 28. Example End-to-End Flow

### 28.1 User Input

```text
我最近准备面试，有点焦虑。回答直接一点，先给结论。
```

### 28.2 Candidate Memories

```json
[
  {
    "layer": "episodic_event",
    "key": "career_event",
    "value": {"event_type": "career.interview_preparation", "status": "open"},
    "confidence": 0.88,
    "authority": "user_explicit",
    "sensitivity": "personal",
    "evidence": "最近准备面试"
  },
  {
    "layer": "semantic_fact",
    "key": "current_emotional_state",
    "value": "anxious",
    "confidence": 0.82,
    "authority": "user_explicit",
    "sensitivity": "sensitive",
    "evidence": "有点焦虑"
  },
  {
    "layer": "preference",
    "key": "communication_style",
    "value": "direct",
    "confidence": 0.93,
    "authority": "user_explicit",
    "sensitivity": "personal",
    "evidence": "回答直接一点"
  },
  {
    "layer": "preference",
    "key": "response_opening",
    "value": "answer_first",
    "confidence": 0.93,
    "authority": "user_explicit",
    "sensitivity": "personal",
    "evidence": "先给结论"
  }
]
```

### 28.3 Query

```text
面试怎么准备？
```

### 28.4 Gate Decisions

```json
[
  {
    "key": "career_event",
    "action": "follow_up",
    "prompt_visibility": "visible",
    "safe_to_mention": true
  },
  {
    "key": "current_emotional_state",
    "action": "style_only",
    "prompt_visibility": "policy_only",
    "safe_to_mention": false
  },
  {
    "key": "communication_style",
    "action": "style_only",
    "prompt_visibility": "policy_only",
    "safe_to_mention": false
  },
  {
    "key": "response_opening",
    "action": "style_only",
    "prompt_visibility": "policy_only",
    "safe_to_mention": false
  }
]
```

### 28.5 Compiled Context

```text
[Direct User Facts]
- The user is preparing for interviews.

[Style Preferences]
- Answer directly.
- Start with the conclusion.
- Keep the response concise.
- Use a calm tone.

[Event Follow-up Cues]
- If useful, ask at most one short question about the interview stage or target role.

[Hidden Constraints]
- Do not explicitly mention the user's anxious state unless they ask for emotional support.
```

---

## 29. Definition of Done for Phase 2

Phase 2 can be considered complete when:

```text
1. The project has schema v2 and normalized storage.
2. LLM extraction can produce validated candidate memories.
3. Rule extraction remains as fallback.
4. Write decisions use configurable policies.
5. Contradiction and correction are handled through supersession.
6. Hybrid retrieval is implemented.
7. MemoryUseGate v2 supports at least 7 actions.
8. Context compiler separates direct facts, style policy, event followups, hidden constraints.
9. At least one event skill is production-ready: career_event_skill.
10. User can review, correct, delete, and disable memories.
11. Evaluation harness exists with at least 100 cases.
12. CI runs unit tests and eval smoke tests.
13. README explains architecture, limitations, and API.
```

---

## 30. Key Design Principles

### 30.1 Retrieval Is Not Usage

A retrieved memory must not automatically enter the answer. It must pass the gate.

### 30.2 Memory Must Be Revisable

Every memory should be correctable, supersedable, or deletable.

### 30.3 Inferred Profile Is Not Fact

Inferred profile should mostly influence style, not content.

### 30.4 Sensitive Memory Requires Stronger Relevance

Sensitive memory should have higher thresholds for direct use.

### 30.5 Event Memory Is a State Machine

Events should track progress, blockers, resolution, and staleness.

### 30.6 Evidence Is First-Class

Memory without evidence is hard to trust and hard to correct.

### 30.7 User Control Is Product Quality

Memory review, correction, and deletion are not optional features; they are core quality controls.

### 30.8 Evaluate Before Optimizing

Do not tune thresholds blindly. Add eval cases first.

---

## 31. Immediate Next Steps

Recommended next implementation sequence:

```text
Week 1:
  - Add tooling and CI.
  - Add schema v2 models.
  - Add normalized SQLite repository.

Week 2:
  - Add MemoryOperationPlanner.
  - Add contradiction detector.
  - Add write evaluator v2.

Week 3:
  - Add LLM extractor interface and prompt.
  - Add validator and repair.
  - Add extraction eval set.

Week 4:
  - Add hybrid retrieval skeleton.
  - Add embedding provider interface.
  - Add gate v2.

Week 5:
  - Add context compiler v2.
  - Add career event skill.
  - Add event follow-up cooldown.

Week 6:
  - Add review APIs.
  - Add memory settings.
  - Add privacy eval.
  - Update docs and README.
```

---

## 32. Appendix: Minimal Phase 2 MVP Scope

If scope must be reduced, build only these first:

```text
1. MemoryRecord / MemoryEvidence / MemoryOperation models
2. Normalized SQLite storage
3. LLM extraction with schema validation
4. Write evaluator v2
5. Hybrid retrieval with keyword + embedding
6. Gate v2 with 7 actions
7. Context compiler v2
8. Career event skill
9. Memory review API
10. Eval harness with 100 cases
```

This is enough to make EvolveMemory substantially more advanced while preserving the existing prototype architecture.

---

## 33. Appendix: Suggested README Update

Add this to README after the current architecture section:

```markdown
## Phase 2 Direction

EvolveMemory is evolving from a prototype memory engine into a memory runtime for personal AI systems.

Phase 2 focuses on:

- LLM-based memory proposal extraction
- schema-validated write decisions
- evidence-backed memory records
- hybrid retrieval with embeddings and temporal scoring
- memory use gating with direct, style-only, follow-up, clarify, hidden-constraint, summarize-only, and suppress actions
- event skills for progress-aware memories
- user review, correction, deletion, and memory settings
- offline evaluation for extraction, retrieval, gating, privacy, and event tracking

The key product principle remains:

> Retrieval is not usage. Every memory must pass a use gate before it can shape an answer.
```

---

## 34. Appendix: Example Developer Checklist

Before merging a memory-related PR:

```text
[ ] Does it preserve user correction priority?
[ ] Does it avoid direct use of inferred profile?
[ ] Does it handle sensitive memory safely?
[ ] Does it write audit events?
[ ] Does it include tests?
[ ] Does it include eval cases if behavior changed?
[ ] Does it avoid prompt leakage of hidden constraints?
[ ] Does it avoid writing third-party facts as user facts?
[ ] Does it support deletion / retirement semantics?
[ ] Does it keep backward compatibility or include migration?
```

---

## 35. Final Recommendation

EvolveMemory 的最大优势不是存储层，而是 **memory usage policy**。Phase 2 应该继续强化这个差异化：

```text
Memory Extraction
+ Memory Lifecycle
+ Memory Use Gate
+ Response Policy Compiler
+ Event Progress Skills
+ User Governance
+ Evaluation Harness
```

如果这个方向做实，EvolveMemory 可以成为一个非常适合 personal AI / agent 系统的 memory governance layer，而不只是另一个向量记忆库。

