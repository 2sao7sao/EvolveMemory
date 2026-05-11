# Adaptive Memory Replay

This replay is the product story EvolveMemory should make obvious: memory should
change the assistant's behavior, but it should not force irrelevant personal
details into every answer.

## Conversation

| Turn | User input | Runtime behavior |
| --- | --- | --- |
| 1 | 我最近准备面试，有点焦虑。 | Writes an evolving event and a sensitive emotional-state memory. |
| 2 | 回答直接一点，先给结论。 | Writes communication-style preferences. |
| 3 | 面试怎么准备？ | Uses the event as `follow_up`, emotion as `summarize_only`, and style as `style_only`. |
| 4 | 今天只帮我 review Python 代码，不用提面试。 | Suppresses the interview event and keeps only the style policy. |
| 5 | 其实我不想让你记住焦虑这件事。 | Routes to correction/deletion so the sensitive state can be retired. |

## Gate Expectations

```json
{
  "interview_query": {
    "life_event": "follow_up",
    "current_emotional_state": "summarize_only",
    "communication_style": "style_only"
  },
  "coding_query_with_no_mention": {
    "life_event": "suppress",
    "communication_style": "style_only"
  }
}
```

## Why This Matters

Many memory systems retrieve what they remember and place it into the prompt.
EvolveMemory separates retrieval from permission:

```text
stored memory -> retrieval planning -> memory use gate -> response policy
```

The goal is not to sound like the assistant remembers everything. The goal is
for the assistant to adapt naturally, stay useful, and avoid awkward recall.

## Metrics to Track

| Metric | Definition |
| --- | --- |
| `use_appropriateness` | Whether selected memories are relevant and safe for the query. |
| `creepy_recall_rate` | How often the assistant mentions a memory that should stay silent. |
| `style_adaptation_score` | Whether preferences change structure and tone without exposing facts. |
| `correction_success_rate` | Whether user corrections retire or update stale memories. |
| `sensitive_suppression_rate` | Whether sensitive facts are blocked unless strongly relevant. |
