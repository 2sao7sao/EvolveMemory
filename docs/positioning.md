# Positioning

## One-Line

EvolveMemory is the memory control plane for AI personalization: it decides what to remember, how to store it, when to use it, how to use it, when to suppress it, and how to turn memory uncertainty into dynamic interaction.

## What EvolveMemory Is

- A **memory governance runtime** that sits between raw user signals and the prompt context layer.
- A **memory-use gate** that separates retrieval from permission — a retrieved memory is only a candidate until policy decides its use.
- A **memory interaction layer** that converts low-confidence decisions into dynamic controls (buttons, confirmations, scope selectors) instead of silent assumptions.

## What EvolveMemory Is Not

- Not a transcript store.
- Not a vector database wrapper.
- Not a universal context API.
- Not a production-hardened service (yet — see Security Checklist).

## Differentiation

| Project | Focus | EvolveMemory difference |
| --- | --- | --- |
| Mem0 | Universal memory layer for AI agents | EvolveMemory focuses on governance, gating, and interaction — not just storage and retrieval. |
| Supermemory | Context stack / RAG / user profiles / connectors | EvolveMemory provides policy between storage and generation: authority, scope, staleness, and dynamic UI controls. |
| Custom RAG | Retrieve-then-generate | EvolveMemory adds write governance, use-gate decisions, lifecycle management, and user-facing controls on top of retrieval. |

## North Star

> Continuously reduce the intervention cost users pay to make a system understand them, while preserving user control over privacy, memory, outcomes, and high-risk actions.

## Core Principles

1. **Retrieval is not permission.** Every retrieved memory passes through a use gate.
2. **LLM output is not the writer of record.** Models propose; deterministic policy decides.
3. **User said ≠ user authorized long-term storage.** Authority and scope must be resolved.
4. **Stale memory is worse than no memory.** Lifecycle management prevents outdated recall.
5. **Interaction should decrease over time.** Cold-start explores; mature phase applies silently.

## Prototype Boundary

This repository is a research prototype. Production deployment requires:

- Authentication and tenant isolation
- Field-level encryption for sensitive values
- Retention policy enforcement
- Observability and alerting
- Security red-team testing

See [SECURITY.md](../SECURITY.md) for details.
