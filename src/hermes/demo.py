"""The two-minute late-buyer demo, driven through the API like the test. `python -m hermes.demo`
resets and seeds DATABASE_URL, then plays the story against a running API (HERMES_API_URL, started
with HERMES_ENV=development), printing each step. The approval is the one human step; here the
seeded supplier is logged in and approves, as the presenter would on the page."""

import os

import httpx
import psycopg

from hermes.dispatcher import drain
from hermes.ledger import db, load
from hermes.synthetic import generate


def play(dsn: str, secret: str, http, say=print, root: str = "storage/synthetic") -> None:
    world = generate(root)
    with psycopg.connect(dsn, autocommit=True) as c:
        db.reset(c)
        load.run(c, root)
    drain(dsn, secret, http)  # the agent reads what loading announced, so the story starts clean
    story = next(i for i in world["invoices"] if i["scenario"] == "late_buyer" and i["supplier"] == "S1")

    def login(who):
        token = http.post("/dev/login", json={"email": who}).json()["token"]
        return {"Authorization": f"Bearer {token}"}

    def ok(r):
        assert r.status_code == 200, r.text
        return r.json()

    ops, approver = login("ops@lender-a.example"), login("supplier@kaveri.example")
    inv = next(i for i in ok(http.get("/v1/invoices", headers=ops)) if i["invoice_no"] == story["invoice_no"])
    say(f"1. Reset and loaded the synthetic set: 3 suppliers, 4 buyers, 30 invoices. The story is "
        f"invoice {inv['invoice_no']}, Rs {inv['total']}, a verified late buyer.")
    inv, principal = inv["id"], f"{float(story['total']) * 0.7:.2f}"
    ok(http.post(f"/v1/invoices/{inv}/advances", headers=ops,
                 json={"principal": principal, "disbursed_on": "2026-09-01"}))
    say(f"2. Lender advances Rs {principal} on 2026-09-01: invoice advanced.")
    ok(http.put("/dev/clock", json={"date": "2026-11-14"}))
    ok(http.post("/dev/tick", json={}))
    say(f"3. Clock set to 2026-11-14 and ticked; the agent ran: {drain(dsn, secret, http)} events (every overdue invoice).")
    view = ok(http.get(f"/v1/invoices/{inv}", headers=ops))
    say(f"   Invoice {view['state']}; claim Rs {view['claim']['claim_value']} "
        f"(interest Rs {view['claim']['interest']}); exposure Rs {view['collateral']['exposure']}.")
    action = next(a for a in ok(http.get("/v1/actions", headers=approver, params={"status": "proposed"}))
                  if a["invoice_id"] == inv and a["kind"] == "settlement_offer")
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
