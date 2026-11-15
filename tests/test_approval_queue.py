"""Ticket 26: the full approval queue through the API. No API key."""

import psycopg
import pytest
from fastapi.testclient import TestClient

from hermes.api import create_app
from test_seeded_invoice_api import SECRET, login, seeded_invoice_id


@pytest.fixture
def db(dsn):
    with psycopg.connect(dsn, autocommit=True) as c:
        c.execute("INSERT INTO app_user (tenant_id, email, role) SELECT tenant_id, "
                  "'hermesops@hermes.example', 'hermes_ops' FROM app_user LIMIT 1")
        yield c


@pytest.fixture
def client(dsn, db):
    return TestClient(create_app(dsn, secret=SECRET, env="development"))


@pytest.fixture
def who(client):
    return {n: login(client, f"{e}@{d}") for n, e, d in (
        ("agent", "agent", "lender-a.example"), ("ops", "ops", "lender-a.example"),
        ("lender", "approver", "lender-a.example"), ("supplier", "supplier", "sundaram.example"),
        ("hermes", "hermesops", "hermes.example"))}


@pytest.fixture
def inv(client, who):
    return seeded_invoice_id(client, who["ops"])


def propose(client, who, inv, kind, **extra):
    r = client.post(f"/v1/invoices/{inv}/actions", headers=who["agent"],
                    json={"kind": kind, "draft": {"summary": f"{kind} draft", "letter": "Hello"},
                          **extra})
    assert r.status_code == 200, r.text
    return r.json()


def queue(client, h):
    r = client.get("/v1/actions", headers=h, params={"status": "proposed"})
    assert r.status_code == 200, r.text
    return r.json()


def test_each_role_sees_only_its_items_sorted_by_deadline(client, who, inv):
    late = propose(client, who, inv, "buyer_note", deadline="2026-12-20")
    soon = propose(client, who, inv, "doc_link", deadline="2026-12-01")
    terms = propose(client, who, inv, "contract_terms")  # no deadline: falls back to due date
    obj = propose(client, who, inv, "objection", deadline="2026-12-10")
    assert [a["id"] for a in queue(client, who["supplier"])] == [soon["id"], obj["id"], late["id"]]
    assert [a["id"] for a in queue(client, who["hermes"])] == [
        terms["id"], soon["id"], obj["id"]]  # due date 2026-09-15 sorts first
    assert queue(client, who["lender"]) == [] and queue(client, who["ops"]) == []


def post(client, h, a, verb, **body):
    return client.post(f"/v1/actions/{a['id']}/{verb}", headers=h, json=body)


def test_edit_is_stored_as_a_difference_then_approval_records_who_when_and_what(client, db, who, inv):
    a = propose(client, who, inv, "buyer_note")
    r = post(client, who["supplier"], a, "edit", changes={"letter": "Hello, revised"})
    assert r.status_code == 200, r.text
    assert r.json()["edit_difference"] == {"letter": {"from": "Hello", "to": "Hello, revised"}}
    assert r.json()["draft"]["letter"] == "Hello"  # the agent's draft is untouched
    assert post(client, who["supplier"], a, "edit", changes={"offer": "1.00"}).status_code == 422
    done = post(client, who["supplier"], a, "approve")
    assert done.status_code == 200, done.text
    d = done.json()
    assert d["status"] == "approved" and d["approved_at"] and d["needs"] == []
    assert d["final_draft"]["letter"] == "Hello, revised"
    assert [(x["email"], x["role"]) for x in d["approvals"]] == [("supplier@sundaram.example", "supplier")]
    after = db.execute("SELECT actor, after FROM audit_log WHERE action='approve'").fetchone()
    assert after[0].startswith("supplier:") and after[1]["edit_difference"]["letter"]["to"] == "Hello, revised"
    assert queue(client, who["supplier"]) == []


def test_rejection_needs_a_reason(client, who, inv):
    a = propose(client, who, inv, "buyer_note")
    assert post(client, who["supplier"], a, "reject").status_code == 422
    assert post(client, who["supplier"], a, "reject", reason="  ").status_code == 422
    r = post(client, who["supplier"], a, "reject", reason="wrong buyer")
    assert r.status_code == 200 and r.json()["status"] == "rejected"
    assert r.json()["reject_reason"] == "wrong buyer"


def test_agent_and_wrong_roles_cannot_decide(client, who, inv):
    a = propose(client, who, inv, "buyer_note")  # supplier only
    t = propose(client, who, inv, "contract_terms")  # hermes_ops only
    for verb, body in (("approve", {}), ("reject", {"reason": "x"}), ("edit", {"changes": {"letter": "x"}})):
        for role in ("agent", "ops", "lender"):
            assert post(client, who[role], a, verb, **body).status_code == 403, (verb, role)
        assert post(client, who["hermes"], a, verb, **body).status_code == 403, verb
        assert post(client, who["supplier"], t, verb, **body).status_code == 403, verb


def test_two_approver_item_shows_who_approved_and_who_is_outstanding(client, db, who, inv):
    a = propose(client, who, inv, "objection")
    assert queue(client, who["supplier"])[0]["needs"] == ["hermes_ops", "supplier"]
    first = post(client, who["supplier"], a, "approve")
    assert first.status_code == 200 and first.json()["status"] == "proposed"
    assert first.json()["needs"] == ["hermes_ops"]
    assert [x["role"] for x in first.json()["approvals"]] == ["supplier"]
    assert post(client, who["supplier"], a, "approve").status_code == 409  # one slot per person
    assert db.execute("SELECT count(*) FROM event_queue WHERE kind='action.approved'").fetchone()[0] == 0
    last = post(client, who["hermes"], a, "approve")
    assert last.status_code == 200 and last.json()["status"] == "approved" and last.json()["needs"] == []
    ev = db.execute("SELECT payload->>'action_id', payload->>'kind', invoice_id::text FROM event_queue "
                    "WHERE kind='action.approved'").fetchall()
    assert ev == [(a["id"], "objection", inv)]


def test_an_edit_clears_earlier_approvals(client, who, inv):
    a = client.post(f"/v1/invoices/{inv}/actions", headers=who["agent"],
                    json={"kind": "objection", "draft": {"raised_on": "2026-01-05"}}).json()
    post(client, who["supplier"], a, "approve")
    r = post(client, who["hermes"], a, "edit", changes={"raised_on": "2026-01-06"})
    assert r.json()["approvals"] == [] and r.json()["needs"] == ["hermes_ops", "supplier"]


def test_supplier_cannot_touch_another_suppliers_item(client, db, who, inv):
    a = propose(client, who, inv, "buyer_note")
    db.execute("INSERT INTO app_user (tenant_id, email, role, supplier_id) SELECT tenant_id, "
               "'s@other.example','supplier',gen_random_uuid() FROM app_user LIMIT 1")
    other = login(client, "s@other.example")
    assert queue(client, other) == []
    assert post(client, other, a, "approve").status_code == 404


def test_a_supplier_login_without_a_supplier_cannot_exist(db):
    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute("INSERT INTO app_user (tenant_id, email, role) SELECT tenant_id, 'x@y.example', "
                   "'supplier' FROM app_user LIMIT 1")


def test_lender_sees_an_approved_offer_in_the_timeline_as_information(client, who, inv):
    a = propose(client, who, inv, "buyer_note")
    assert post(client, who["supplier"], a, "approve").status_code == 200
    events = client.get(f"/v1/invoices/{inv}/timeline", headers=who["lender"]).json()
    assert any(e.get("event") == "action.approved" and e["payload"]["action_id"] == a["id"]
               for e in events)
