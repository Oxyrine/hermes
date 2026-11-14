"""Ticket 13: audit trail, idempotent writes and role checks through the API."""

import psycopg
import pytest
from fastapi.testclient import TestClient

from hermes.api import create_app
from test_seeded_invoice_api import SECRET, login, seeded_invoice_id


@pytest.fixture
def db(dsn):
    with psycopg.connect(dsn, autocommit=True) as c:
        yield c


@pytest.fixture
def client(dsn):
    return TestClient(create_app(dsn, secret=SECRET, env="development"))


ADV = {"principal": "700000.00", "disbursed_on": "2026-09-01"}


def test_advance_writes_an_audit_row_with_actor_object_before_and_after(client, db):
    h = login(client)
    inv = seeded_invoice_id(client, h)
    assert client.post(f"/v1/invoices/{inv}/advances", headers=h, json=ADV).status_code == 200
    row = db.execute("SELECT actor, action, object_type, object_id::text, before->>'state', "
                     "after->>'state', at FROM audit_log WHERE action='POST /v1/invoices/{id}/advances'"
                     ).fetchone()
    assert row[0].startswith("lender_ops:")
    assert (row[2], row[3], row[4], row[5]) == ("invoice", inv, "verified", "advanced")
    assert row[6] is not None


def test_audit_log_and_ims_events_reject_update_and_delete(client, db):
    h = login(client)
    inv = seeded_invoice_id(client, h)
    client.post(f"/v1/invoices/{inv}/advances", headers=h, json=ADV)
    for sql in ("UPDATE audit_log SET actor='x'", "DELETE FROM audit_log",
                "UPDATE ims_event SET action='pending'", "DELETE FROM ims_event"):
        with pytest.raises(psycopg.errors.RaiseException):
            db.execute(sql)


def test_repeated_idempotency_key_returns_first_response_and_writes_nothing(client, db):
    h = login(client) | {"Idempotency-Key": "k-1"}
    inv = seeded_invoice_id(client, h)
    first = client.post(f"/v1/invoices/{inv}/advances", headers=h, json=ADV)
    again = client.post(f"/v1/invoices/{inv}/advances", headers=h, json=ADV)
    assert first.status_code == again.status_code == 200 and again.json() == first.json()
    assert db.execute("SELECT count(*) FROM advance").fetchone()[0] == 1
    assert db.execute("SELECT count(*) FROM audit_log WHERE action LIKE 'POST%advances'"
                      ).fetchone()[0] == 1
    other = {**ADV, "principal": "1.00"}
    assert client.post(f"/v1/invoices/{inv}/advances", headers=h, json=other).status_code == 422


def test_roles_follow_the_spec(client):
    ops, appr = login(client), login(client, "approver@lender-a.example")
    agent = login(client, "agent@lender-a.example")
    inv = seeded_invoice_id(client, ops)
    adv = f"/v1/invoices/{inv}/advances"
    assert client.post(adv, headers=agent, json=ADV).status_code == 403
    assert client.post(adv, headers=appr, json=ADV).status_code == 403
    assert client.post("/v1/actions/00000000-0000-0000-0000-000000000000/approve",
                       headers=agent).status_code == 403
    assert client.post("/v1/actions/00000000-0000-0000-0000-000000000000/reject",
                       headers=ops).status_code == 403
    eng = {"invoice_id": inv, "inputs": {"delivery": "2026-08-01", "written_days": 45}}
    assert client.post("/v1/engines/deadline/run", headers=ops, json=eng).status_code == 403
    assert client.post("/v1/engines/deadline/run", headers=agent, json=eng).status_code == 200
    assert client.get("/v1/actions", headers=agent).status_code == 403


def test_supplier_sees_only_own_invoices_and_no_ops_endpoints(client, dsn):
    with psycopg.connect(dsn, autocommit=True) as c:
        sup = c.execute("SELECT id FROM supplier").fetchone()[0]
        t = c.execute("SELECT id FROM tenant").fetchone()[0]
        c.execute("INSERT INTO app_user (tenant_id, email, role, supplier_id) "
                  "VALUES (%s,'s@own.example','supplier',%s)", (t, sup))
        c.execute("INSERT INTO app_user (tenant_id, email, role, supplier_id) VALUES "
                  "(%s,'s@other.example','supplier',gen_random_uuid())", (t,))
    inv = seeded_invoice_id(client, login(client))
    own, other = login(client, "s@own.example"), login(client, "s@other.example")
    assert [r["id"] for r in client.get("/v1/invoices", headers=own).json()] == [inv]
    assert client.get("/v1/invoices", headers=other).json() == []
    assert client.get(f"/v1/invoices/{inv}", headers=own).status_code == 200
    for path in ("", "/timeline", "/collateral-series", "/receipts", "/documents"):
        assert client.get(f"/v1/invoices/{inv}{path}", headers=other).status_code == 404, path
    assert client.post(f"/v1/invoices/{inv}/advances", headers=own, json=ADV).status_code == 403


def test_reading_receipts_and_documents_is_audited(client, db):
    h = login(client)
    inv = seeded_invoice_id(client, h)
    assert client.get(f"/v1/invoices/{inv}/documents", headers=h).status_code == 200
    assert client.get(f"/v1/invoices/{inv}/receipts", headers=h).status_code == 200
    rows = db.execute("SELECT action, object_id::text FROM audit_log WHERE action LIKE 'read:%' "
                      "ORDER BY id").fetchall()
    assert rows == [("read:documents", inv), ("read:receipts", inv)]
