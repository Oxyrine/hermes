"""Ticket 14: two-person bank rate, through the HTTP API."""

from decimal import Decimal

import psycopg
import pytest
from fastapi.testclient import TestClient

from hermes.api import create_app
from hermes.dispatcher import drain
from test_advance_clock_overdue import advance
from test_seeded_invoice_api import SECRET, login, seeded_invoice_id

SOURCE = "https://example.test/rbi-release"


@pytest.fixture
def client(dsn):
    return TestClient(create_app(dsn, secret=SECRET, env="development"))


@pytest.fixture
def db(dsn):
    with psycopg.connect(dsn, autocommit=True) as c:
        yield c


def enter(client, h, day="2026-10-12", rate="6.25"):
    return client.post("/v1/admin/bank-rates", headers=h,
                       json={"effective_from": day, "rate": rate, "source_url": SOURCE})


def test_an_entered_rate_is_pending_and_unused_until_a_second_person_approves(client):
    one, two = login(client), login(client, "ops2@lender-a.example")
    inv = seeded_invoice_id(client, one)
    client.put("/dev/clock", json={"date": "2026-11-14"})
    before = client.get(f"/v1/invoices/{inv}", headers=one).json()["claim"]["claim_value"]

    r = enter(client, one)
    assert r.status_code == 200, r.text
    rows = client.get("/v1/admin/bank-rates", headers=one).json()
    new = next(x for x in rows if x["effective_from"] == "2026-10-12")
    assert (new["status"], new["rate"], new["source_url"]) == ("pending", "6.250000", SOURCE)
    assert client.get(f"/v1/invoices/{inv}", headers=one).json()["claim"]["claim_value"] == before

    assert client.post("/v1/admin/bank-rates/2026-10-12/approve", headers=one).status_code == 409
    assert client.post("/v1/admin/bank-rates/2026-10-12/approve", headers=two).status_code == 200
    rows = client.get("/v1/admin/bank-rates", headers=one).json()
    assert next(x for x in rows if x["effective_from"] == "2026-10-12")["status"] == "approved"
    assert Decimal(client.get(f"/v1/invoices/{inv}", headers=one).json()["claim"]["claim_value"]) > Decimal(before)


def test_a_mid_period_rate_changes_only_the_rests_after_its_effective_date(client):
    one, two = login(client), login(client, "ops2@lender-a.example")
    inv = seeded_invoice_id(client, one)

    def claim(as_of):
        return client.get(f"/v1/invoices/{inv}", headers=one, params={"as_of": as_of}).json()["claim"]

    first_rest, later = claim("2026-10-15"), claim("2026-11-14")
    enter(client, one)  # effective 2026-10-12, inside the first rest (after the 2026-10-07 rate, before the 2026-10-16 rest)
    client.post("/v1/admin/bank-rates/2026-10-12/approve", headers=two)
    assert claim("2026-10-15")["claim_value"] == first_rest["claim_value"]  # first rest keeps the old rate
    assert Decimal(claim("2026-11-14")["claim_value"]) > Decimal(later["claim_value"])  # second rest uses 6.25


def test_self_approval_is_refused_by_the_database_as_well(client, db):
    one = login(client)
    enter(client, one)
    uid = db.execute("SELECT entered_by FROM bank_rate WHERE effective_from='2026-10-12'").fetchone()[0]
    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute("UPDATE bank_rate SET approved_by=%s WHERE effective_from='2026-10-12'", (uid,))


def test_approval_fans_out_to_overdue_invoices_and_the_agent_recomputes_them(client, db, dsn):
    one, two = login(client), login(client, "ops2@lender-a.example")
    inv = seeded_invoice_id(client, one)
    advance(client, one, inv)
    client.put("/dev/clock", json={"date": "2026-11-14"})
    client.post("/dev/tick", json={})
    drain(dsn, SECRET, client)
    assert db.execute("SELECT state FROM invoice").fetchone()[0] == "overdue"

    def runs():
        return dict(db.execute("SELECT engine, count(*) FROM engine_run WHERE invoice_id=%s "
                               "AND engine IN ('interest','collateral') GROUP BY engine", (inv,)).fetchall())

    before = runs()
    enter(client, one)
    assert db.execute("SELECT count(*) FROM event_queue WHERE kind='bank_rate.changed'").fetchone()[0] == 0
    client.post("/v1/admin/bank-rates/2026-10-12/approve", headers=two)
    assert db.execute("SELECT invoice_id::text FROM event_queue WHERE kind='bank_rate.changed'"
                      ).fetchall() == [(inv,)]
    assert drain(dsn, SECRET, client) == 1
    after = runs()
    assert after["interest"] == before["interest"] + 1 and after["collateral"] == before["collateral"] + 1
    assert db.execute("SELECT state FROM invoice").fetchone()[0] == "overdue"
