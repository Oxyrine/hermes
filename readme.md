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

`DATABASE_URL` in `.env` already matches. CI needs no database, model call or API key.

## Layout

- `src/hermes/` engines, API, adapters, agent, synthetic data (one Python project)
- `web/` Next.js app (placeholder)
- `docs/` product spec, prototype spec and tickets, ADRs
