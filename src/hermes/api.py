"""HTTP API. Every route authenticates a signed token carrying tenant and role, and every query
is filtered by that tenant. `create_app(dsn, secret, env)`; `app` is built from the environment
for uvicorn (HERMES_ENV defaults to production, so the development login is opt-in)."""

import os
import time
from datetime import date

import jwt
import psycopg
from fastapi import Body, Depends, FastAPI, Header, HTTPException, Response
from psycopg.rows import dict_row

from hermes import statement
from hermes.ledger import db, service, states

TOKEN_TTL_SECONDS = 8 * 3600
NOINDEX = {"X-Robots-Tag": "noindex, nofollow"}


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

    if env == "development":  # the clock exists only here

        @app.put("/dev/clock")
        def set_clock(body: dict = Body(...), c=Depends(conn)):
            service.set_clock(c, date.fromisoformat(body["date"]))
            return {"date": body["date"]}

        @app.post("/dev/tick")
        def tick(body: dict = Body(...), c=Depends(conn)):
            d = date.fromisoformat(body["date"]) if body.get("date") else service.today(c)
            return service.tick(c, d)

    def require(who, *roles):
        if who["role"] not in roles:
            raise HTTPException(403, "role not permitted")

    if env == "development":  # receipts are entered by hand; no payment rail exists yet

        @app.post("/dev/payments")
        def payment(body: dict = Body(...), who=Depends(caller), c=Depends(conn)):
            require(who, "lender_ops")
            try:
                on = date.fromisoformat(body["paid_on"]) if body.get("paid_on") else service.today(c)
                return service.record_payment(c, who["tenant"], body["invoice_id"], body["amount"],
                                              on, body.get("utr"), f"user:{who['sub']}")
            except service.NotFound:
                raise HTTPException(404, "invoice not found") from None
            except (ValueError, KeyError, TypeError, ArithmeticError) as e:
                raise HTTPException(422, f"bad payment: {e}") from None

    @app.post("/v1/invoices/{invoice_id}/waterfall")
    def waterfall(invoice_id: str, body: dict = Body(...), who=Depends(caller), c=Depends(conn)):
        require(who, "agent", "hermes_ops")
        try:
            as_of = date.fromisoformat(body["as_of"]) if body.get("as_of") else service.today(c)
            return service.run_waterfall(c, who["tenant"], invoice_id, as_of)
        except service.NotFound:
            raise HTTPException(404, "invoice not found") from None
        except states.Refused as e:
            raise HTTPException(409, str(e)) from None
        except (ValueError, KeyError, TypeError) as e:
            raise HTTPException(422, f"bad request: {e}") from None

    @app.post("/v1/invoices/{invoice_id}/lender-confirm")
    def lender_confirm(invoice_id: str, who=Depends(caller), c=Depends(conn)):
        require(who, "lender_ops")
        try:
            service.confirm_repayment(c, who["tenant"], invoice_id, f"user:{who['sub']}")
            return {"state": "closed"}
        except service.NotFound:
            raise HTTPException(404, "invoice not found") from None
        except states.Refused as e:
            raise HTTPException(409, str(e)) from None

    @app.post("/v1/invoices/{invoice_id}/advances")
    def advance(invoice_id: str, body: dict = Body(...), who=Depends(caller), c=Depends(conn)):
        require(who, "lender_ops")
        try:
            on = date.fromisoformat(body["disbursed_on"]) if body.get("disbursed_on")                 else service.today(c)
            return service.record_advance(c, who["tenant"], invoice_id, body["principal"], on,
                                          f"user:{who['sub']}")
        except service.NotFound:
            raise HTTPException(404, "invoice not found") from None
        except states.Refused as e:
            raise HTTPException(409, str(e)) from None
        except (ValueError, KeyError, TypeError, ArithmeticError) as e:
            raise HTTPException(422, f"bad advance: {e}") from None

    @app.post("/v1/invoices/{invoice_id}/state")
    def move_state(invoice_id: str, body: dict = Body(...), who=Depends(caller), c=Depends(conn)):
        """The agent's write path: guards are evaluated server-side from the ledger."""
        require(who, "agent", "hermes_ops")
        try:
            as_of = date.fromisoformat(body["as_of"]) if body.get("as_of") else service.today(c)
            service.move_state(c, who["tenant"], invoice_id, body["to"], as_of,
                               f"{who['role']}:{who['sub']}")
            return {"state": body["to"]}
        except service.NotFound:
            raise HTTPException(404, "invoice not found") from None
        except states.Refused as e:
            raise HTTPException(409, str(e)) from None
        except (ValueError, KeyError, TypeError) as e:
            raise HTTPException(422, f"bad request: {e}") from None

    @app.post("/v1/invoices/{invoice_id}/actions")
    def propose(invoice_id: str, body: dict = Body(...), who=Depends(caller), c=Depends(conn)):
        require(who, "agent", "hermes_ops")
        try:
            if body.get("kind") != "settlement_offer":
                raise ValueError("only settlement_offer is supported")
            as_of = date.fromisoformat(body["as_of"]) if body.get("as_of") else service.today(c)
            return service.propose_settlement_offer(c, who["tenant"], invoice_id, as_of,
                                                    f"{who['role']}:{who['sub']}")
        except service.NotFound:
            raise HTTPException(404, "invoice not found") from None
        except states.Refused as e:
            raise HTTPException(409, str(e)) from None
        except (ValueError, KeyError, TypeError) as e:
            raise HTTPException(422, f"bad request: {e}") from None

    def decide(action_id, who, c, approve, reason=None):
        require(who, "lender_approver")
        try:
            out = service.decide_action(c, who["tenant"], action_id, who["sub"], approve, reason)
            if approve and out["kind"] == "settlement_offer":  # the offer goes with a signed link
                out["buyer_link"] = "/public/statement/" + statement.make_token(
                    secret, who["tenant"], out["invoice_id"])
            return out
        except service.NotFound:
            raise HTTPException(404, "action not found") from None
        except states.Refused as e:
            raise HTTPException(409, str(e)) from None

    @app.post("/v1/actions/{action_id}/approve")
    def approve(action_id: str, who=Depends(caller), c=Depends(conn)):
        return decide(action_id, who, c, True)

    @app.post("/v1/actions/{action_id}/reject")
    def reject(action_id: str, body: dict = Body(default={}), who=Depends(caller), c=Depends(conn)):
        return decide(action_id, who, c, False, body.get("reason"))

    @app.get("/v1/actions")
    def actions(status: str | None = None, who=Depends(caller), c=Depends(conn)):
        return service.list_actions(c, who["tenant"], status)

    @app.get("/v1/invoices/{invoice_id}/timeline")
    def timeline(invoice_id: str, who=Depends(caller), c=Depends(conn)):
        try:
            return service.timeline(c, who["tenant"], invoice_id)
        except service.NotFound:
            raise HTTPException(404, "invoice not found") from None

    @app.get("/v1/invoices/{invoice_id}/collateral-series")
    def collateral_series(invoice_id: str, who=Depends(caller), c=Depends(conn)):
        try:
            return service.collateral_series(c, who["tenant"], invoice_id)
        except service.NotFound:
            raise HTTPException(404, "invoice not found") from None

    @app.get("/v1/invoices")
    def invoices(who=Depends(caller), c=Depends(conn)):
        return service.list_invoices(c, who["tenant"])

    @app.get("/v1/invoices/{invoice_id}")
    def invoice(invoice_id: str, as_of: date | None = None, who=Depends(caller), c=Depends(conn)):
        try:
            return service.invoice_view(c, who["tenant"], invoice_id, as_of or service.today(c))
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

    @app.get("/public/statement/{token}")
    def buyer_statement(token: str, response: Response, c=Depends(conn)):
        response.headers.update(NOINDEX)
        try:
            return statement.statement(c, secret, token)
        except statement.Refused:
            raise HTTPException(404, "This link is not valid.", headers=NOINDEX) from None

    @app.post("/public/statement/{token}/respond")
    def buyer_respond(token: str, response: Response, body: dict = Body(...), c=Depends(conn)):
        response.headers.update(NOINDEX)
        try:
            return statement.respond(c, secret, token, body.get("choice"), body.get("note"))
        except statement.Refused:
            raise HTTPException(404, "This link is not valid.", headers=NOINDEX) from None
        except ValueError as e:
            raise HTTPException(422, str(e)) from None

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
