"""Ticket 12: the late-buyer story through the API, the clock and approval calls. No API key."""

from decimal import Decimal

import psycopg
import pytest
from fastapi.testclient import TestClient

from hermes.api import create_app
from hermes.dispatcher import drain
from test_advance_clock_overdue import late_buyer, state
from test_seeded_invoice_api import SECRET, login, seeded_invoice_id


@pytest.fixture
def db(dsn):
    with psycopg.connect(dsn, autocommit=True) as c:
        yield c


@pytest.fixture
def client(dsn):
    return TestClient(create_app(dsn, secret=SECRET, env="development"))


@pytest.fixture
def overdue(client, dsn):
    h = login(client)
    inv = seeded_invoice_id(client, h)
    late_buyer(client, h, inv)
    assert drain(dsn, SECRET, client) == 1
    return h, inv


def pending(client, who):
    r = client.get("/v1/actions", headers=who, params={"status": "proposed"})
    assert r.status_code == 200, r.text
    return r.json()


def test_overdue_proposes_one_offer_that_cites_its_engine_runs_and_sends_nothing(client, db, overdue):
    h, inv = overdue
    approver = login(client, "approver@lender-a.example")
    (a,) = pending(client, approver)
    assert a["invoice_id"] == inv and a["kind"] == "settlement_offer" and a["status"] == "proposed"
    d = a["draft"]
    claim = client.get(f"/v1/invoices/{inv}", headers=h).json()["claim"]
    assert d["offer"] == claim["claim_value"]  # discount 0: principal plus statutory interest
    assert "Dear Meridian Heavy Engineering" in d["letter"]
    assert {c["engine"] for c in d["cites"]} >= {"deadline", "interest", "collateral", "settlement"}
    assert all(c["rule_version"] and c["input_hash"] for c in d["cites"])
    assert state(db, inv) == "overdue"
    assert db.execute("SELECT count(*) FROM action_request WHERE status='sent'").fetchone()[0] == 0
    agent = login(client, "agent@lender-a.example")  # proposing again returns the same action
    again = client.post(f"/v1/invoices/{inv}/actions", headers=agent,
                        json={"kind": "settlement_offer", "as_of": "2026-11-14"})
    assert again.status_code == 200 and again.json()["id"] == a["id"]
    assert len(pending(client, approver)) == 1


def test_approval_records_the_named_user_and_moves_the_invoice_to_settlement_offered(
        client, db, overdue):
    h, inv = overdue
    approver = login(client, "approver@lender-a.example")
    (a,) = pending(client, approver)
    assert client.post(f"/v1/actions/{a['id']}/approve", headers=h).status_code == 403
    r = client.post(f"/v1/actions/{a['id']}/approve", headers=approver)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "approved" and r.json()["approved_at"]
    who = db.execute("SELECT u.email FROM action_request a JOIN app_user u ON u.id=a.approved_by"
                     ).fetchone()
    assert who == ("approver@lender-a.example",)
    assert state(db, inv) == "settlement_offered"
    assert pending(client, approver) == []
    assert client.post(f"/v1/actions/{a['id']}/approve", headers=approver).status_code == 409


def test_rejection_leaves_the_invoice_overdue(client, db, overdue):
    _h, inv = overdue
    approver = login(client, "approver@lender-a.example")
    (a,) = pending(client, approver)
    r = client.post(f"/v1/actions/{a['id']}/reject", headers=approver, json={"reason": "too low"})
    assert r.status_code == 200 and r.json()["status"] == "rejected"
    assert state(db, inv) == "overdue"
    assert db.execute("SELECT reject_reason FROM action_request").fetchone() == ("too low",)


def test_late_buyer_story_end_to_end(client, db, dsn, overdue):
    """Advance, clock, tick, approval, payment, waterfall, lender confirmation; API calls only."""
    h, inv = overdue
    approver = login(client, "approver@lender-a.example")
    (a,) = pending(client, approver)
    assert client.post(f"/v1/actions/{a['id']}/approve", headers=approver).status_code == 200
    offer = a["draft"]["offer"]

    assert client.put("/dev/clock", json={"date": "2026-11-20"}).status_code == 200
    short = client.post("/dev/payments", headers=h, json={
        "invoice_id": inv, "amount": "100000.00", "utr": "UTR-1"})
    assert short.status_code == 200, short.text
    assert drain(dsn, SECRET, client) == 1
    assert state(db, inv) == "settlement_offered"  # not covered yet: no waterfall
    assert client.get(f"/v1/invoices/{inv}", headers=h).json()["waterfall"] is None

    paid = Decimal(offer) - Decimal("100000.00")
    assert client.post("/dev/payments", headers=h, json={
        "invoice_id": inv, "amount": str(paid), "utr": "UTR-2"}).status_code == 200
    assert drain(dsn, SECRET, client) == 1
    assert state(db, inv) == "paid"
    w = client.get(f"/v1/invoices/{inv}", headers=h).json()["waterfall"]
    assert Decimal(w["receipts"]) == Decimal(offer)
    assert (Decimal(w["lender_exposure"]) + Decimal(w["costs"]) + Decimal(w["supplier"])
            == Decimal(offer))
    assert Decimal(w["supplier"]) > 0 and Decimal(w["lender_exposure"]) > Decimal(700000)
    assert db.execute("SELECT status FROM advance").fetchone() == ("open",)

    agent = login(client, "agent@lender-a.example")
    assert client.post(f"/v1/invoices/{inv}/lender-confirm", headers=agent).status_code == 403
    assert client.post(f"/v1/invoices/{inv}/lender-confirm", headers=h).status_code == 200
    assert state(db, inv) == "closed"
    assert db.execute("SELECT status, repaid_on::text FROM advance").fetchone() == (
        "repaid", "2026-11-20")


def test_lender_cannot_close_before_the_waterfall_has_run(client, overdue):
    h, inv = overdue
    assert client.post(f"/v1/invoices/{inv}/lender-confirm", headers=h).status_code == 409


def test_demo_script_plays_from_a_fresh_reset(client, dsn):
    from hermes.demo import play

    lines = []
    play(dsn, SECRET, client, lines.append)
    assert lines[0].startswith("1. Reset") and lines[-1].endswith("invoice closed.")
    play(dsn, SECRET, client, lines.append)  # and again, from clean
