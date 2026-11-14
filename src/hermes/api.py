"""HTTP API. Every route authenticates a signed token carrying tenant and role, and every query
is filtered by that tenant. `create_app(dsn, secret, env)`; `app` is built from the environment
for uvicorn (HERMES_ENV defaults to production, so the development login is opt-in)."""

import os
import time
from datetime import date

import jwt
import psycopg
from fastapi import Body, Depends, FastAPI, Header, HTTPException
from psycopg.rows import dict_row

from hermes.ledger import db, service, states

TOKEN_TTL_SECONDS = 8 * 3600


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
            proposers = {"settlement_offer": service.propose_settlement_offer,
                         "odr_pack": service.propose_dispute_pack}
            if body.get("kind") not in proposers:
                raise ValueError("only settlement_offer and odr_pack are supported")
            as_of = date.fromisoformat(body["as_of"]) if body.get("as_of") else service.today(c)
            return proposers[body["kind"]](c, who["tenant"], invoice_id, as_of,
                                           f"{who['role']}:{who['sub']}")
        except service.NotFound:
            raise HTTPException(404, "invoice not found") from None
        except states.Refused as e:
            raise HTTPException(409, str(e)) from None
        except (ValueError, KeyError, TypeError) as e:
            raise HTTPException(422, f"bad request: {e}") from None

    def person_step(who, c, invoice_id, call, *args):
        """Steps a named person takes after acting outside Hermes (filing, an award, a refusal)."""
        require(who, "lender_ops", "hermes_ops")
        try:
            call(c, who["tenant"], invoice_id, *args, service.today(c), f"user:{who['sub']}")
            return {"state": c.execute("SELECT state FROM invoice WHERE id=%s",
                                       (invoice_id,)).fetchone()[0]}
        except service.NotFound:
            raise HTTPException(404, "invoice not found") from None
        except states.Refused as e:
            raise HTTPException(409, str(e)) from None
        except (ValueError, KeyError, TypeError) as e:
            raise HTTPException(422, f"bad request: {e}") from None

    @app.post("/v1/invoices/{invoice_id}/case-number")
    def case_number(invoice_id: str, body: dict = Body(...), who=Depends(caller), c=Depends(conn)):
        return person_step(who, c, invoice_id, service.record_case_number, body.get("case_number"))

    @app.post("/v1/invoices/{invoice_id}/award")
    def award(invoice_id: str, body: dict = Body(...), who=Depends(caller), c=Depends(conn)):
        return person_step(who, c, invoice_id, service.record_award, body.get("filename"),
                           body.get("content_base64"))

    @app.post("/v1/invoices/{invoice_id}/offer-refused")
    def offer_refused(invoice_id: str, who=Depends(caller), c=Depends(conn)):
        require(who, "lender_ops", "hermes_ops")
        try:
            service.refuse_offer(c, who["tenant"], invoice_id, f"user:{who['sub']}", service.today(c))
            return {"status": "refused"}
        except service.NotFound:
            raise HTTPException(404, "invoice not found") from None
        except states.Refused as e:
            raise HTTPException(409, str(e)) from None

    def decide(action_id, who, c, approve, reason=None):
        require(who, "lender_approver", "supplier")  # which of the two, by kind, is the service's call
        try:
            return service.decide_action(c, who["tenant"], action_id, who["sub"], who["role"],
                                         approve, reason)
        except PermissionError as e:
            raise HTTPException(403, str(e)) from None
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

    @app.get("/v1/actions/{action_id}/pack.{fmt}")
    def pack(action_id: str, fmt: str, who=Depends(caller), c=Depends(conn)):
        """Download the dispute pack (JSON or PDF) from its approval item. Read-only."""
        from fastapi.responses import Response

        from hermes.engines.settlement.pdf import render_pdf

        if fmt not in ("json", "pdf"):
            raise HTTPException(404, "pack formats are json and pdf")
        try:
            body, render = service.dispute_pack(c, who["tenant"], action_id)
        except service.NotFound:
            raise HTTPException(404, "dispute pack not found") from None
        if fmt == "json":
            return body
        return Response(render_pdf(render), media_type="application/pdf",
                        headers={"content-disposition": 'attachment; filename="dispute-pack.pdf"'})

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
