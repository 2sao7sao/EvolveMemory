# Security Policy

EvolveMemory may process sensitive user preferences, events, emotional state, and
profile signals. Treat all real user data as private by default.

## Do Not Commit

- API keys, tokens, cookies, or credentials.
- Real user transcripts or memory stores.
- Local SQLite files or generated session JSON.
- Debug exports that include personal data.

## Reporting

Open a GitHub issue for non-sensitive security hardening suggestions. For
sensitive vulnerabilities or privacy leaks, contact the repository owner
privately and avoid posting exploit details publicly.

## Current Boundaries

- This repository is a prototype, not a hardened production memory service.
- Demo data is synthetic.
- Production deployments must add authentication, tenant isolation, encryption,
  retention policy, and observability.
