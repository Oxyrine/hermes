# Hermes

Hermes is the evidence, pricing and servicing layer between MSME suppliers and regulated lenders. It reads an invoice's documents, scores the evidence, computes the statutory interest, deadlines and collateral value with deterministic versioned code, and drafts the next action (a settlement offer, a letter, a dispute pack) for a named person to approve. Models read documents; they never compute a date or a rupee, and nothing leaves the system without a person's approval. Hermes never lends, takes receivables, files anything or gives legal advice.

This is a prototype on synthetic data, local-first. Product spec: [docs/product-spec.md](docs/product-spec.md). Prototype spec, tickets and decisions: [docs/prototype/](docs/prototype/), [docs/adr/](docs/adr/). Checklist audit and dependency scan: [docs/prototype/checklists.md](docs/prototype/checklists.md).

## Run it

```
uv sync                      # Python 3.12 and dependencies
docker compose up -d db      # PostgreSQL 16 on localhost:5432
cp .env.example .env         # local config (git-ignored); GEMINI_API_KEY is only for live model runs
uv run ruff check . && uv run pytest
```

No Docker: install PostgreSQL 16 locally and create user `hermes` (password `hermes-local-only`) and database `hermes`. Tests need no database setup (they start an embedded PostgreSQL 16 when `DATABASE_URL` is unset), no API key and no network.

```
uv run python -m hermes.ledger.seed                    # reset and seed DATABASE_URL (dev only)
HERMES_ENV=development uv run uvicorn hermes.api:app   # API on :8000
uv run python -m hermes.dispatcher                     # the agent: works the event queue
cd web && npm install && npm run dev                   # web app on :3000
```

Outside development, `HERMES_ENV` defaults to production: the development login, clock and payment endpoints are off and `HERMES_TOKEN_SECRET` must be set.

## Run the demo

The late-buyer story takes two minutes and makes no model calls: the demo agent is the scripted runner, and a test asserts it.

1. Run the seed command above (it resets the database to the synthetic set), start the API and the web app, open :3000.
2. Follow [docs/prototype/demo-script.md](docs/prototype/demo-script.md). Replay by running the seed command again.
3. Without a browser: `uv run python -m hermes.demo` plays the whole story against the running API and prints each step; the recorded output is [docs/prototype/walkthrough.txt](docs/prototype/walkthrough.txt).

## Not in the prototype

- Real data, real lenders, real filings: synthetic documents and fixture adapters stand in for GST, e-invoice, Udyam and bank sources.
- Real user authentication: there are no passwords or sessions; a development-only login issues signed tokens for seeded users.
- Deployment: no cloud, no HTTPS, no HSTS (ticket 35, deferred). Local Postgres, local files and a database-backed queue stand in for Cloud SQL, storage and Pub/Sub.
- Managed agent in the demo: the Gemini function-calling loop is the default; the managed-agent spike worked with caveats (ADR 0002) and stays off.
- Marketing pages, privacy policy, terms, analytics, cookie banner: none. Items that need owner decisions are listed in the checklist audit.
- Pro models: free-tier Flash and Flash-Lite only.

## Layout

- `src/hermes/` engines, API, adapters, agent, synthetic data (one Python project)
- `web/` Next.js app (invoice page, portfolio, supplier app, onboarding, buyer statement)
- `docs/` product spec, prototype spec and tickets, ADRs, checklist audit
