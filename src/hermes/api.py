"""HTTP API. Every route authenticates a signed token carrying tenant and role, and every query
is filtered by that tenant. `create_app(dsn, secret, env)`; `app` is built from the environment
for uvicorn (HERMES_ENV defaults to production, so the development login is opt-in)."""

import os
import time
from datetime import date, datetime
from zoneinfo import ZoneInfo

import jwt
import psycopg
from fastapi import Body, Depends, FastAPI, Header, HTTPException
from psycopg.rows import dict_row

from hermes.ledger import db, service

TOKEN_TTL_SECONDS = 8 * 3600


def today_ist() -> date:
    return datetime.now(ZoneInfo("Asia/Kolkata")).date()


def create_app(dsn: str, secret: str, env: str = "production") -> FastAPI:
    app = FastAPI(title="Hermes", version="0.0.0")

    def conn():
        with psycopg.connect(dsn, autocommit=True) as c:
            yield c

    def caller(authorization: str | None = Header(default=None)) -> dict:
        try:
            scheme, _, token = (authorization or "").partition(" ")
            if scheme.lower() != "bearer":
                raise jwt.InvalidTokenError
            claims = jwt.decode(token, secret, algorithms=["HS256"], options={"require": ["tenant", "role", "exp"]})
        except jwt.InvalidTokenError:
            raise HTTPException(401, "invalid or missing token") from None
        return claims

    if env == "development":  # the development login exists only here

        @app.post("/dev/login")
        def dev_login(body: dict = Body(...), c=Depends(conn)):
            row = c.cursor(row_factory=dict_row).execute(
                "SELECT id::text, tenant_id::text, role FROM app_user WHERE email=%s",
                (body.get("email"),)).fetchone()
            if row is None:
                raise HTTPException(404, "unknown seeded user")
            token = jwt.encode(
                {"sub": row["id"], "tenant": row["tenant_id"], "role": row["role"],
                 "exp": int(time.time()) + TOKEN_TTL_SECONDS}, secret, algorithm="HS256")
            return {"token": token, "role": row["role"]}

    @app.get("/v1/invoices")
    def invoices(who=Depends(caller), c=Depends(conn)):
        return service.list_invoices(c, who["tenant"])

    @app.get("/v1/invoices/{invoice_id}")
    def invoice(invoice_id: str, as_of: date | None = None, who=Depends(caller), c=Depends(conn)):
        try:
            return service.invoice_view(c, who["tenant"], invoice_id, as_of or today_ist())
        except service.NotFound:
            raise HTTPException(404, "invoice not found") from None

    @app.post("/v1/engines/{engine}/run")
    def run_engine(engine: str, body: dict = Body(...), who=Depends(caller), c=Depends(conn)):
        try:
            return service.run_engine(c, who["tenant"], body.get("invoice_id"), engine,
                                      body["inputs"])
        except service.NotFound:
            raise HTTPException(404, "engine or invoice not found") from None
        except (ValueError, KeyError, TypeError) as e:
            raise HTTPException(422, f"engine rejected inputs: {e}") from None

    return app


def _from_env() -> FastAPI:
    env = os.environ.get("HERMES_ENV", "production")
    secret = os.environ.get("HERMES_TOKEN_SECRET") or (
        "dev-only-secret-do-not-use-0123456789" if env == "development" else "")
    if not secret:
        raise RuntimeError("HERMES_TOKEN_SECRET must be set outside development")
    return create_app(db.database_url(), secret, env)


def __getattr__(name):  # `uvicorn hermes.api:app` builds the app lazily; imports stay side-effect free
    if name == "app":
        return _from_env()
    raise AttributeError(name)
