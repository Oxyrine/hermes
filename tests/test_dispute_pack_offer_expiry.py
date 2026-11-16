"""Ticket 23: offer expiry, dispute pack, supplier release, case number, award. No API key."""

from decimal import Decimal

import psycopg
import pytest
from fastapi.testclient import TestClient

from hermes.api import create_app
from hermes.dispatcher import drain
from test_advance_clock_overdue import late_buyer, state
from test_offer_approval_close import pending
from test_seeded_invoice_api import SECRET, login, seeded_invoice_id


@pytest.fixture
def db(dsn):
    with psycopg.connect(dsn, autocommit=True) as c:
        yield c


@pytest.fixture
def client(dsn):
    return TestClient(create_app(dsn, secret=SECRET, env="development"))


@pytest.fixture
def offered(client, dsn):
    """Late buyer, offer proposed on 2026-11-14 and approved: invoice settlement_offered."""
    h = login(client)
    inv = seeded_invoice_id(client, h)
    late_buyer(client, h, inv)
    drain(dsn, SECRET, client)
    approver = login(client, "supplier@sundaram.example")
    (a,) = pending(client, approver)
    assert client.post(f"/v1/actions/{a['id']}/approve", headers=approver).status_code == 200
    return h, inv, a


def tick(client, day):
    assert client.put("/dev/clock", json={"date": day}).status_code == 200
    assert client.post("/dev/tick", json={}).status_code == 200


def events(db, kind):
    return db.execute("SELECT invoice_id::text FROM event_queue WHERE kind=%s", (kind,)).fetchall()


def test_offer_carries_an_expiry_and_the_tick_emits_offer_expired_once_it_passes(
        client, db, offered):
    _h, inv, a = offered
    assert a["expires_on"] == "2026-11-21"
    tick(client, "2026-11-21")  # the last day of the offer: not yet expired
    assert events(db, "offer.expired") == []
    tick(client, "2026-11-22")
    assert events(db, "offer.expired") == [(inv,)]
    tick(client, "2026-11-23")  # once only
    assert len(events(db, "offer.expired")) == 1
    assert db.execute("SELECT status FROM action_request").fetchone() == ("expired",)


@pytest.fixture
def expired(client, dsn, offered):
    h, inv, _ = offered
    tick(client, "2026-11-22")
    drain(dsn, SECRET, client)
    supplier = login(client, "supplier@sundaram.example")
    (pack,) = [a for a in pending(client, supplier) if a["kind"] == "odr_pack"]
    return h, inv, supplier, pack


def test_expiry_proposes_a_dispute_pack_whose_figures_equal_the_stored_engine_runs(
        client, db, expired):
    h, inv, _supplier, pack = expired
    assert pack["invoice_id"] == inv and pack["status"] == "proposed"
    assert state(db, inv) == "settlement_offered"  # moves only when the supplier consents
    sheet = pack["draft"]["pack"]["claim_computation"]
    stored = {(r[0], r[1], r[2]): r[3] for r in db.execute(
        "SELECT engine, rule_version, inputs_hash, outputs FROM engine_run WHERE invoice_id=%s",
        (inv,)).fetchall()}
    assert {r["engine"] for r in sheet["runs"]} >= {"deadline", "interest", "collateral"}
    for r in sheet["runs"]:  # each cited run is a stored run, with the same result
        assert stored[(r["engine"], r["rule_version"], r["input_hash"])]["result"] == r["result"]
    interest = next(r for r in sheet["runs"] if r["engine"] == "interest")["result"]
    rows = {r["item"]: r["amount"] for r in sheet["rows"]}
    claim = client.get(f"/v1/invoices/{inv}", headers=h, params={"as_of": "2026-11-22"}).json()
    assert Decimal(rows["statutory_claim"]) == Decimal(interest["claim"]).quantize(Decimal("0.01")) == Decimal(
        claim["claim"]["claim_value"])
    assert pack["draft"]["pack"]["document_index"]  # seeded documents are indexed
    r = client.get(f"/v1/actions/{pack['id']}/pack.json", headers=h)
    assert r.status_code == 200 and r.json()["claim_computation"] == sheet
    r = client.get(f"/v1/actions/{pack['id']}/pack.pdf", headers=h)
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf"
    assert r.content.startswith(b"%PDF") and rows["statutory_claim"].encode() in r.content
    assert client.get(f"/v1/actions/{pack['id']}/pack.pdf").status_code == 401


def test_only_the_supplier_releases_the_pack_and_approval_records_who_and_when(
        client, db, expired):
    h, inv, supplier, pack = expired
    approver = login(client, "approver@lender-a.example")
    assert client.post(f"/v1/actions/{pack['id']}/approve", headers=approver).status_code == 403
    assert client.post(f"/v1/actions/{pack['id']}/approve", headers=h).status_code == 403
    r = client.post(f"/v1/actions/{pack['id']}/approve", headers=supplier)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "approved" and r.json()["approved_at"]
    assert db.execute("SELECT u.email FROM action_request a JOIN app_user u ON u.id=a.approved_by "
                      "WHERE a.kind='odr_pack'").fetchone() == ("supplier@sundaram.example",)
    assert state(db, inv) == "odr_ready"
    assert client.post(f"/v1/actions/{pack['id']}/approve", headers=supplier).status_code == 409


def test_the_lender_approver_cannot_approve_an_offer_at_or_above_the_floor(client, dsn):
    h = login(client)
    inv = seeded_invoice_id(client, h)
    late_buyer(client, h, inv)
    drain(dsn, SECRET, client)
    (a,) = pending(client, login(client, "supplier@sundaram.example"))  # the supplier's to approve
    lender = login(client, "approver@lender-a.example")
    assert pending(client, lender) == []
    assert client.post(f"/v1/actions/{a['id']}/approve", headers=lender).status_code == 403


@pytest.fixture
def ready(client, expired):
    h, inv, supplier, pack = expired
    assert client.post(f"/v1/actions/{pack['id']}/approve", headers=supplier).status_code == 200
    return h, inv


def test_filed_only_when_a_person_enters_the_case_number_then_awarded_with_a_document(
        client, db, ready):
    h, inv = ready
    agent = login(client, "agent@lender-a.example")
    case = f"/v1/invoices/{inv}/case-number"
    assert client.post(case, headers=agent, json={"case_number": "MSEFC-1"}).status_code == 403
    assert client.post(case, headers=h, json={"case_number": "  "}).status_code == 422
    assert state(db, inv) == "odr_ready"
    assert client.post(case, headers=h, json={"case_number": "MSEFC/KA/2026/0042"}).status_code == 200
    assert state(db, inv) == "odr_filed"
    assert db.execute("SELECT case_number FROM invoice").fetchone() == ("MSEFC/KA/2026/0042",)

    award = f"/v1/invoices/{inv}/award"
    assert client.post(award, headers=h, json={}).status_code == 422  # no document, no award
    assert client.post(award, headers=h, json={"filename": "a.pdf", "content_base64": ""}
                       ).status_code == 422
    assert state(db, inv) == "odr_filed"
    r = client.post(award, headers=h, json={"filename": "award.pdf", "content_base64": "JVBERi0="})
    assert r.status_code == 200, r.text
    assert state(db, inv) == "awarded"
    assert db.execute("SELECT doc_type, sha256 FROM document WHERE doc_type='award'"
                      ).fetchone()[0] == "award"


def test_case_number_is_refused_before_the_supplier_releases_the_pack(client, db, expired):
    h, inv, _, _ = expired
    r = client.post(f"/v1/invoices/{inv}/case-number", headers=h, json={"case_number": "X-1"})
    assert r.status_code == 409 and state(db, inv) == "settlement_offered"


def test_a_refused_offer_also_leads_to_a_pack(client, db, dsn, offered):
    h, inv, _ = offered
    agent = login(client, "agent@lender-a.example")
    assert client.post(f"/v1/invoices/{inv}/offer-refused", headers=agent).status_code == 403
    assert client.post(f"/v1/invoices/{inv}/offer-refused", headers=h).status_code == 200
    assert drain(dsn, SECRET, client) >= 1
    supplier = login(client, "supplier@sundaram.example")
    assert [a["kind"] for a in pending(client, supplier)] == ["odr_pack"]
    assert db.execute("SELECT status FROM action_request WHERE kind='settlement_offer'"
                      ).fetchone() == ("expired",)


def test_no_code_path_contacts_the_dispute_portal():
    import pathlib

    import hermes

    src = "\n".join(p.read_text(encoding="utf-8").lower()
                    .replace('httpx.post(f"https://generativelanguage', "")  # agent.py's Gemini call, ticket 22
                    for p in pathlib.Path(hermes.__file__).parent.rglob("*.py")
                    # outbound callers: lender endpoints (ticket 33), Gemini API (ticket 17), Groq fallback
                    if p.name not in ("webhooks.py", "llm.py", "groq.py"))
    for needle in ("httpx.post", "requests.", "urllib", "odr.msme", "samadhaan", "socket"):
        assert needle not in src.replace("self.http.request", ""), needle
