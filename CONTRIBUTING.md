# Contributing to EvolveMemory

EvolveMemory is an adaptive memory runtime. Contributions should improve memory
write quality, retrieval planning, use gating, response adaptation, correction,
privacy, or evaluation.

## Development Setup

```bash
python -m pip install -r requirements.txt
python -m pytest -q
python -m evals.runner --suite gate_eval
python examples/replay_adaptive_memory.py
```

## Good Contributions

| Area | Examples |
| --- | --- |
| Memory write policy | Better duplicate, contradiction, review, and retirement rules. |
| Use gate | More precise direct/style/follow-up/suppress decisions. |
| Conversation experience | Replay demos that show subtle adaptation without awkward recall. |
| Privacy | Sensitive memory suppression, user correction, forget-all, audit export. |
| Evals | Multi-turn noisy conversations, stale memory, correction conflicts, multilingual cases. |
| Integrations | Chatbot, workflow, and agent harness examples. |

## Quality Bar

- Add deterministic tests for behavior changes.
- Add or update eval cases when changing memory gate semantics.
- Keep demos synthetic and free of private user data.
- Do not commit local SQLite files, session data, API keys, or raw user traces.
- Prefer explicit metrics over subjective claims.

## Pull Request Checklist

- `python -m pytest -q` passes.
- `python -m evals.runner --suite gate_eval` passes.
- README or examples are updated for user-facing behavior changes.
- Privacy and correction behavior are considered.
