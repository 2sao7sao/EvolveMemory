# EvolveMemory Adaptive Replay

This replay is the product path EvolveMemory should make obvious: memory should
adapt the assistant without forcing private details into the answer.

## Scenario

The user gives two signals:

```text
1. 我最近准备面试，有点焦虑。
2. 回答直接一点，先给结论。
```

A simple memory system might retrieve both memories and inject them into every
future prompt. EvolveMemory uses the memory gate to decide which memories are
allowed to shape the current answer.

## Run It

```bash
python -m memory_system.demo
```

or:

```bash
python examples/replay_adaptive_memory.py
```

## Expected Output Shape

```text
# EvolveMemory Adaptive Replay

status: PASS
active_memories_before_correction: 7
accepted_candidates: 4/4
gate_eval: 8/8

## 1. Interview query actions
- life_event: follow_up
- communication_style: style_only
- response_opening: style_only

## 3. Suppressed memories
- life_event: suppress

## 4. Product metrics
- gate_action_accuracy: 1.00 (8/8)
- explicit_suppression_rate: 1.00 (1/1)
- style_continuity_rate: 1.00 (4/4)
- prompt_safety_rate: 1.00 (1/1)
- correction_retirement_rate: 1.00 (2/2)
```

## What The Metrics Mean

| Metric | Definition | Why it matters |
| --- | --- | --- |
| `gate_action_accuracy` | Share of expected gate actions matched by regression cases. | Retrieval must not automatically become prompt use. |
| `explicit_suppression_rate` | Whether an explicit no-mention request suppresses matching event memory. | User intent must override memory recall. |
| `style_continuity_rate` | Whether style preferences still shape relevant and unrelated queries. | Memory should adapt behavior without exposing private facts. |
| `prompt_safety_rate` | Whether no direct visible memory is injected for the no-mention query. | Avoids creepy or unnecessary recall. |
| `correction_retirement_rate` | Whether correction retires the sensitive state and derived profile memory. | Forgetting must remove behavioral residue, not only raw records. |

## Gate Expectations

| Query | Expected behavior |
| --- | --- |
| `面试怎么准备？` | `life_event -> follow_up`; style preferences stay `style_only`. |
| `今天只帮我 review Python 代码，不用提面试。` | `life_event -> suppress`; style preferences stay `style_only`. |
| `其实我不想让你记住焦虑这件事。` | Retire `current_emotional_state` and derived `emotional_support_need`. |

## Product Boundary

This replay uses deterministic rule extraction and deterministic gate logic. It
does not claim to solve all personal-memory cases. It proves a concrete runtime
contract: a memory must pass write policy, retrieval, use gate, prompt-safety,
and correction checks before it can influence an answer.
