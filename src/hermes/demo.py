"""The two-minute late-buyer demo, driven through the API like the test. `python -m hermes.demo`
resets and seeds DATABASE_URL, then plays the story against a running API (HERMES_API_URL, started
with HERMES_ENV=development), printing each step. The approval is the one human step; here the
seeded supplier is logged in and approves, as the presenter would on the page."""

import os

import httpx
import psycopg

from hermes.dispatcher import drain
from hermes.ledger import db, seed


def play(dsn: str, secret: str, http, say=print) -> None:
    with psycopg.connect(dsn, autocommit=True) as c:
        db.reset(c)
        seed.run(c)
    say("1. Reset and seeded: one verified invoice, Rs 1000000.00, due 2026-09-15.")

    def login(who):
        token = http.post("/dev/login", json={"email": who}).json()["token"]
        return {"Authorization": f"Bearer {token}"}

    def ok(r):
        assert r.status_code == 200, r.text
        return r.json()

    ops, approver = login("ops@lender-a.example"), login("supplier@sundaram.example")
    inv = ok(http.get("/v1/invoices", headers=ops))[0]["id"]
    ok(http.post(f"/v1/invoices/{inv}/advances", headers=ops,
                 json={"principal": "700000.00", "disbursed_on": "2026-09-01"}))
    say("2. Lender advances Rs 700000.00 on 2026-09-01: invoice advanced.")
    ok(http.put("/dev/clock", json={"date": "2026-11-14"}))
    ok(http.post("/dev/tick", json={}))
    say(f"3. Clock set to 2026-11-14 and ticked; the agent ran: {drain(dsn, secret, http)} event.")
    view = ok(http.get(f"/v1/invoices/{inv}", headers=ops))
    say(f"   Invoice {view['state']}; claim Rs {view['claim']['claim_value']} "
        f"(interest Rs {view['claim']['interest']}); exposure Rs {view['collateral']['exposure']}.")
    (action,) = ok(http.get("/v1/actions", headers=approver, params={"status": "proposed"}))
    say(f"4. Approval list: settlement offer of Rs {action['draft']['offer']} proposed.")
    ok(http.post(f"/v1/actions/{action['id']}/approve", headers=approver))
    say("5. Approver approves: invoice settlement_offered.")
    ok(http.post("/dev/payments", headers=ops, json={
        "invoice_id": inv, "amount": action["draft"]["offer"], "paid_on": "2026-11-20",
        "utr": "UTR-DEMO"}))
    ok(http.put("/dev/clock", json={"date": "2026-11-20"}))
    drain(dsn, secret, http)
    w = ok(http.get(f"/v1/invoices/{inv}", headers=ops))["waterfall"]
    say(f"6. Buyer pays Rs {w['receipts']}: invoice paid. Waterfall: lender Rs {w['lender_exposure']}, "
        f"costs Rs {w['costs']}, supplier Rs {w['supplier']}.")
    ok(http.post(f"/v1/invoices/{inv}/lender-confirm", headers=ops))
    say(f"7. Lender confirms repayment: invoice {ok(http.get(f'/v1/invoices/{inv}', headers=ops))['state']}.")


if __name__ == "__main__":
    play(db.database_url(), os.environ.get("HERMES_TOKEN_SECRET", "dev-only-secret-do-not-use-0123456789"),
         httpx.Client(base_url=os.environ.get("HERMES_API_URL", "http://localhost:8000")))
