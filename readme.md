# Hermes

Evidence, pricing and servicing layer between MSME suppliers and regulated lenders. Prototype on synthetic data, local-first. Product spec: [docs/product-spec.md](docs/product-spec.md). Prototype spec and tickets: [docs/prototype/](docs/prototype/).

## Setup

```
uv sync                      # install Python 3.12 + dependencies
docker compose up -d db      # PostgreSQL 16 on localhost:5432
cp .env.example .env         # local config (git-ignored)
uv run ruff check . && uv run pytest
```

**No Docker?** Install PostgreSQL 16 locally (Windows installer or `brew install postgresql@16`), then:

```
createuser hermes -P         # password: hermes-local-only
createdb -O hermes hermes
```

`DATABASE_URL` in `.env` already matches. CI needs no model call or API key.

**Tests need no database setup.** Without `DATABASE_URL`, `uv run pytest` starts an embedded
PostgreSQL 16 (dev dependency `pixeltable-pgserver`); with it set, tests use that server and
wipe its `public` schema, so point it at a scratch database.

## Run the first slice

```
uv run python -m hermes.ledger.seed                    # reset and seed DATABASE_URL (dev only)
HERMES_ENV=development uv run uvicorn hermes.api:app   # API on :8000, /dev/login enabled
cd web && npm install && npm run dev                   # invoice page on :3000
```

## Layout

- `src/hermes/` engines, API, adapters, agent, synthetic data (one Python project)
- `web/` Next.js app (invoice page)
- `docs/` product spec, prototype spec and tickets, ADRs
