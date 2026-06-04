# Gate Decision Rules

## Overview

The Memory Use Gate decides how a retrieved memory may influence the current answer. It produces one of seven actions per memory candidate.

## Actions

### use_directly

The memory appears as a visible fact in the response.

**Conditions:** High relevance, low sensitivity, high authority, not expired, user has not asked to suppress.

**Forbidden:** Sensitive memory, expired memory, user said "don't mention this."

**Example:** "你之前说你用 Python。"

---

### style_only

The memory shapes tone, structure, or approach without being mentioned.

**Conditions:** Communication preference, style preference, procedural memory.

**Forbidden:** User explicitly disabled personalization.

**Example:** Use "conclusion first" structure without saying "I remember you prefer conclusions first."

---

### follow_up

A short progress question about an open event.

**Conditions:** Open event, strong relevance, not fatigued, cooldown respected.

**Forbidden:** Unrelated query, user said "don't bring this up", fatigue limit reached.

**Example:** "上次你提到面试，如果还相关……"

---

### hidden_constraint

An internal policy constraint not visible to the user.

**Conditions:** Safety limits, privacy constraints, negative preferences.

**Forbidden:** Facts that require transparent disclosure.

**Example:** Internally avoid recommending a style the user dislikes.

---

### clarify

Ask whether the memory is still true before using it.

**Conditions:** Memory may be stale, conflicting, or low-confidence but high-impact.

**Forbidden:** Low-impact unrelated memory.

**Example:** "你现在还在准备面试吗？"

---

### summarize_only

Use only as aggregate context without exposing details.

**Conditions:** Sensitive but necessary as background context.

**Forbidden:** User opted out.

**Example:** "近期有职业变化相关背景" (no specifics).

---

### suppress

Memory is not used in the prompt at all. Audit record only.

**Conditions:** User disabled, sensitive but irrelevant, expired, user said "don't mention this."

**Forbidden:** High-risk safety constraints that must remain active.

**Example:** Memory about past anxiety when query is about Python syntax.

---

## Decision Flow

```text
Retrieved Memory
  → Is explicitly suppressed by query? → suppress
  → Is never_prompt? → suppress
  → Is expired / deleted? → suppress
  → Is low score (< 0.48)? → suppress
  → Is inferred profile? → style_only
  → Is preference? → style_only or hidden_constraint
  → Is sensitive + low relevance? → summarize_only
  → Is open event needing progress? → follow_up
  → Else → use_directly
```

## Thresholds (gate-v3.0)

| Action | Score threshold |
| --- | --- |
| use_directly | 0.82 |
| style_only | 0.65 |
| follow_up | 0.75 |
| clarify | 0.55 |
| summarize_only | 0.50 |
| suppress | 0.00 |

## Sensitivity Rules

| Sensitivity | Direct allowed | Review required | Default action |
| --- | --- | --- | --- |
| public | yes | no | use_directly |
| personal | yes | no | use_directly |
| sensitive | no | yes | summarize_only |
| restricted | no | yes | suppress |
