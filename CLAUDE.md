# CLAUDE.md

Hermes prototype. Read `CONTEXT.md` (glossary) and `docs/adr/` before changing behaviour.

- Models read documents; deterministic versioned code computes every date and rupee; a named person approves anything that leaves the system.
- Engines: JSON in, JSON out, no network/model/DB. Change an engine or its rule file => bump its rule version.
- Single write path: everything writes through the HTTP API. The agent has no DB access.
- Money: 28-digit Decimal in engines, strings in JSON, paisa rounding only at the API boundary.
- Hermes never lends, takes receivables, files anything, or gives legal advice. No code path may do so.
- Tests need no API key and no network. Live-model runs are manual.
- Secrets come from the environment or git-ignored `.env`. Never commit them.
- Commits: owner's identity only, no assistant attribution.
- Tickets: `docs/prototype/issues/`. Spec: `docs/prototype/spec.md`.
