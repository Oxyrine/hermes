# 01: Repo and skeleton

**What to build:** A developer can clone Hermes, start the database, run the test suite and see CI go green. Hermes lives in its own private repository with one Python project (engines, API, adapters, agent, synthetic data), a placeholder Next.js app, PostgreSQL 16 in Docker, and a domain glossary seeded from the product spec's terms table.

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

- [ ] Private repository exists and the first commit is pushed, authored with the owner's identity only (no assistant attribution)
- [ ] One command installs Python dependencies; one command starts PostgreSQL 16
- [ ] If Docker is unavailable on the machine, a local PostgreSQL 16 path is documented and works
- [ ] Lint and an empty test suite run locally and in CI on every push; CI makes no model calls and needs no API key
- [ ] Project guidance file, domain glossary and a decisions record exist; the decisions record lists the prototype's departures from the product spec (local-first, free-tier models, loop-first agent, schema additions, state-machine additions, part-payment convention, GSTR-2B deemed acceptance, waterfall, injected clock)
- [ ] The product spec and this feature's spec and tickets are in the repository
- [ ] Secrets are read from the environment and an ignored local file; nothing secret is committed
