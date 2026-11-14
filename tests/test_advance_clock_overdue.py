"""Ticket 11: state machine, advance, clock, tick, dispatcher and scripted agent, via the API."""

from decimal import Decimal

import psycopg
import pytest
from fastapi.testclient import TestClient

from hermes.api import create_app
from hermes.dispatcher import drain
from hermes.ledger import states
from test_seeded_invoice_api import SECRET, login, seeded_invoice_id


@pytest.fixture
def db(dsn):
    with psycopg.connect(dsn, autocommit=True) as c:
        yield c


def seeded(db):
    return db.execute("SELECT id::text, tenant_id::text FROM invoice").fetchone()


def state(db, inv):
    return db.execute("SELECT state FROM invoice WHERE id=%s", (inv,)).fetchone()[0]


def test_state_machine_refuses_what_the_table_or_guard_forbids(db):
    inv, tenant = seeded(db)
    with pytest.raises(states.Refused):  # not in the table
        states.transition(db, tenant, inv, "closed", {}, "test")
    with pytest.raises(states.Refused):  # band D fails the guard
        states.transition(db, tenant, inv, "financeable", {"band": "D", "eligibility": "eligible"}, "test")
    with pytest.raises(states.Refused):  # ineligible fails the guard
        states.transition(db, tenant, inv, "financeable", {"band": "A", "eligibility": "ineligible"}, "test")
    assert state(db, inv) == "verified"
    states.transition(db, tenant, inv, "financeable", {"band": "C", "eligibility": "eligible"}, "test")
    assert state(db, inv) == "financeable"
    log = db.execute("SELECT action, before->>'state', after->>'state' FROM audit_log").fetchall()
    assert log == [("state_change", "verified", "financeable")]


@pytest.fixture
def client(dsn):
    return TestClient(create_app(dsn, secret=SECRET, env="development"))


def test_recording_an_advance_moves_verified_to_advanced_and_moves_no_money(client, db):
    h = login(client)
    inv = seeded_invoice_id(client, h)
    r = client.post(f"/v1/invoices/{inv}/advances", headers=h,
                    json={"principal": "700000.00", "disbursed_on": "2026-09-01"})
    assert r.status_code == 200, r.text
    assert db.execute("SELECT principal::text, nominal_rate::text, disbursed_on::text FROM advance"
                      ).fetchall() == [("700000.00", "18.000000", "2026-09-01")]
    assert state(db, inv) == "advanced"
    assert db.execute("SELECT count(*) FROM payment").fetchone()[0] == 0
    assert client.get(f"/v1/invoices/{inv}", headers=h).json()["state"] == "advanced"
    too_big = client.post(f"/v1/invoices/{inv}/advances", headers=h,
                          json={"principal": "2000000.00"})
    assert too_big.status_code in (409, 422)
    supplier = login(client, "agent@lender-a.example")
    assert client.post(f"/v1/invoices/{inv}/advances", headers=supplier,
                       json={"principal": "1.00"}).status_code == 403


def advance(client, h, inv, on="2026-09-01"):
    r = client.post(f"/v1/invoices/{inv}/advances", headers=h,
                    json={"principal": "700000.00", "disbursed_on": on})
    assert r.status_code == 200, r.text


def test_clock_is_injected_and_tick_emits_deadline_passed_and_snapshots(client, db):
    h = login(client)
    inv = seeded_invoice_id(client, h)
    advance(client, h, inv)
    assert client.put("/dev/clock", json={"date": "2026-09-10"}).status_code == 200
    assert client.get(f"/v1/invoices/{inv}", headers=h).json()["claim"]["as_of"] == "2026-09-10"
    assert client.post("/dev/tick", json={}).status_code == 200  # ticks the clock's date
    assert db.execute("SELECT count(*) FROM event_queue").fetchone()[0] == 0  # due 2026-09-15
    snap = db.execute("SELECT as_of::text, claim_value::text, exposure::text FROM collateral_snapshot"
                      ).fetchall()
    assert [s[0] for s in snap] == ["2026-09-10"] and snap[0][1] == "1000000.00"

    client.put("/dev/clock", json={"date": "2026-11-14"})
    for _ in range(2):  # a repeated tick must not queue the same event twice
        client.post("/dev/tick", json={})
    ev = db.execute("SELECT kind, payload->>'as_of', invoice_id::text FROM event_queue").fetchall()
    assert ev == [("deadline.passed", "2026-11-14", inv)]
    snap = {s[0]: s[1:] for s in db.execute(
        "SELECT as_of::text, claim_value, exposure FROM collateral_snapshot").fetchall()}
    assert Decimal(snap["2026-11-14"][0]) > Decimal(1000000) and snap["2026-11-14"][1] > 0


def test_clock_endpoints_do_not_exist_outside_development(dsn):
    prod = TestClient(create_app(dsn, secret=SECRET, env="production"))
    assert prod.put("/dev/clock", json={"date": "2026-11-14"}).status_code == 404
    assert prod.post("/dev/tick", json={}).status_code == 404



def late_buyer(client, h, inv):
    advance(client, h, inv)
    client.put("/dev/clock", json={"date": "2026-11-14"})
    client.post("/dev/tick", json={})


def test_advance_clock_tick_drain_makes_the_invoice_overdue(client, db, dsn):
    h = login(client)
    inv = seeded_invoice_id(client, h)
    late_buyer(client, h, inv)
    assert state(db, inv) == "advanced"
    assert drain(dsn, SECRET, client) == 1

    body = client.get(f"/v1/invoices/{inv}", headers=h).json()
    assert body["state"] == "overdue"
    assert Decimal(body["claim"]["claim_value"]) > Decimal("1000000.00")
    assert db.execute("SELECT count(*) FROM event_queue WHERE done_at IS NULL").fetchone()[0] == 0
    run = db.execute("SELECT runner, status, tool_calls FROM agent_run").fetchone()
    assert run[0] == "scripted" and run[1] == "ok" and run[2] >= 2
    assert drain(dsn, SECRET, client) == 0

    tl = client.get(f"/v1/invoices/{inv}/timeline", headers=h).json()
    kinds = [(t["kind"], t.get("engine") or t.get("to") or t.get("event")) for t in tl]
    assert kinds.index(("event", "deadline.passed")) < kinds.index(("state_change", "overdue"))
    assert ("engine_run", "interest") in kinds and ("engine_run", "collateral") in kinds
    assert [t["to"] for t in tl if t["kind"] == "state_change"] == [
        "financeable", "advanced", "overdue"]
    assert [t["at"] for t in tl] == sorted(t["at"] for t in tl)


def test_a_locked_invoice_is_not_touched_by_a_second_run(client, db, dsn):
    h = login(client)
    inv = seeded_invoice_id(client, h)
    late_buyer(client, h, inv)
    with psycopg.connect(dsn, autocommit=True) as other:
        other.execute("SELECT pg_advisory_lock(hashtext(%s))", (inv,))
        assert drain(dsn, SECRET, client) == 0
        assert state(db, inv) == "advanced"
    assert drain(dsn, SECRET, client) == 1
    assert state(db, inv) == "overdue"


def test_only_the_agent_or_ops_may_move_state_and_guards_still_apply(client, db):
    h = login(client)
    inv = seeded_invoice_id(client, h)
    body = {"to": "overdue", "as_of": "2026-11-14"}
    assert client.post(f"/v1/invoices/{inv}/state", headers=h, json=body).status_code == 403
    agent = login(client, "agent@lender-a.example")
    early = client.post(f"/v1/invoices/{inv}/state", headers=agent,
                        json={"to": "overdue", "as_of": "2026-09-01"})
    assert early.status_code == 409  # not past due
    assert client.post(f"/v1/invoices/{inv}/state", headers=agent, json=body).status_code == 200
    assert state(db, inv) == "overdue"


def test_collateral_series_serves_the_chart_from_snapshots(client):
    h = login(client)
    inv = seeded_invoice_id(client, h)
    advance(client, h, inv)
    for d in ("2026-09-10", "2026-11-14"):
        client.put("/dev/clock", json={"date": d})
        client.post("/dev/tick", json={})
    pts = client.get(f"/v1/invoices/{inv}/collateral-series", headers=h).json()
    assert [p["as_of"] for p in pts] == ["2026-09-10", "2026-11-14"]
    assert pts[0]["claim_value"] == "1000000.00"
    assert Decimal(pts[1]["claim_value"]) > Decimal(pts[0]["claim_value"])
    assert Decimal(pts[1]["exposure"]) > Decimal(pts[0]["exposure"]) > 0


def test_only_the_state_machine_writes_invoice_state():
    from pathlib import Path

    src = Path(states.__file__).parents[1]
    offenders = [p.name for p in src.rglob("*.py")
                 if p.name != "states.py" and "SET state" in p.read_text(encoding="utf-8")]
    assert offenders == []
