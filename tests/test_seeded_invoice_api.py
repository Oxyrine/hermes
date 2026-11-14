"""Ticket 10 through the HTTP API seam: login, invoice read, engine run, tenant isolation."""

from decimal import Decimal

import psycopg
import pytest
from fastapi.testclient import TestClient

from hermes.api import create_app
from hermes.engines.collateral import run as collateral_run
from hermes.engines.deadline import engine as deadline
from hermes.engines.eligibility import run as eligibility_run
from hermes.engines.evidence import run as evidence_run
from hermes.engines.interest import run as interest_run

AS_OF = "2026-11-14"
SECRET = "test-secret-not-for-production-0123456789"
RATES = [
    {"effective_from": "2025-12-05", "rate_percent": "5.500000"},
    {"effective_from": "2026-10-07", "rate_percent": "5.750000"},
]


@pytest.fixture
def client(dsn):
    return TestClient(create_app(dsn, secret=SECRET, env="development"))


def login(client, email="ops@lender-a.example"):
    r = client.post("/dev/login", json={"email": email})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def seeded_invoice_id(client, headers):
    r = client.get("/v1/invoices", headers=headers)
    assert r.status_code == 200
    (row,) = r.json()
    return row["id"]


def read(client, headers, as_of=AS_OF):
    return client.get(f"/v1/invoices/{seeded_invoice_id(client, headers)}",
                      params={"as_of": as_of}, headers=headers)


def test_invoice_read_figures_equal_engine_outputs(client):
    h = login(client)
    body = read(client, h).json()

    # Expected values come from calling the engines directly on hand-written literals.
    dl = deadline.run({"delivery": "2026-08-01", "written_days": 45})["result"]
    assert dl["due"] == "2026-09-15" and dl["interest_from"] == "2026-09-16"
    assert body["deadline"]["due"] == dl["due"]
    assert body["deadline"]["acceptance"] == dl["acceptance"]
    assert body["deadline"]["interest_from"] == dl["interest_from"]
    assert body["deadline"]["rule_version"] == deadline.RULES["version"]

    el = eligibility_run({
        "udyam_urn": "UDYAM-KA-18-0002002", "registration_date": "2021-04-01",
        "enterprise_type": "manufacturing", "classification": "small",
        "contract_date": "2026-05-10", "supply_date": "2026-08-01"})["result"]
    assert body["eligibility"]["status"] == el["status"] == "eligible"

    claim = interest_run({
        "principal": "1000000.00", "interest_start": "2026-09-16", "as_of": AS_OF,
        "bank_rates": RATES})["result"]
    assert body["claim"]["claim_value"] == claim["claim_display"]
    assert body["claim"]["principal"] == "1000000.00"
    want = Decimal(claim["claim_display"]) - Decimal("1000000.00")
    assert Decimal(body["claim"]["interest"]) == want > 0
    assert body["claim"]["as_of"] == AS_OF

    ev = evidence_run({"as_of": AS_OF, "signals": [
        {"type": t, "source": None} for t in
        ("irn_valid_matching", "ewb_matching", "grn_matching", "po_matching", "ims_accepted")
    ]})["result"]
    assert (body["evidence"]["score"], body["evidence"]["band"]) == (ev["score"], ev["band"])
    assert {c["signal"]: c["points"] for c in body["evidence"]["contributions"]} == {
        c["signal"]: c["points"] for c in ev["contributions"]}
    assert all(c["source"] for c in body["evidence"]["contributions"])

    col = collateral_run({
        "eligibility": "eligible", "band": ev["band"], "principal": "1000000.00",
        "due_date": dl["due"], "as_of": AS_OF, "statutory_claim": claim["claim"],
        "lender_rate_percent": "18", "bank_rate_percent": "5.75"})["result"]
    assert body["collateral"]["exposure"] == col["exposure_display"]
    assert body["collateral"]["alerts"] == col["alerts"]
    assert body["state"] == "verified"
    assert body["invoice_no"] == "AC/2026/0412" and body["total"] == "1000000.00"


def test_reading_before_interest_starts_claims_principal(client):
    body = read(client, login(client), as_of="2026-09-01").json()
    assert body["claim"]["claim_value"] == "1000000.00"
    assert Decimal(body["claim"]["interest"]) == 0


def test_requests_without_a_valid_token_are_rejected(client):
    assert client.get("/v1/invoices").status_code == 401
    assert client.get("/v1/invoices", headers={"Authorization": "Bearer junk"}).status_code == 401


def test_dev_login_does_not_exist_outside_development(dsn):
    prod = TestClient(create_app(dsn, secret=SECRET, env="production"))
    assert prod.post("/dev/login", json={"email": "ops@lender-a.example"}).status_code == 404


def test_other_tenants_user_sees_nothing(client, dsn):
    with psycopg.connect(dsn, autocommit=True) as c:
        t = c.execute("INSERT INTO tenant (name, kind) VALUES ('Lender B','nbfc') RETURNING id"
                      ).fetchone()[0]
        c.execute("INSERT INTO app_user (tenant_id, email, role) "
                  "VALUES (%s,'agent@lender-b.example','agent')", (t,))
    mine = login(client)
    invoice_id = seeded_invoice_id(client, mine)
    theirs = login(client, "agent@lender-b.example")
    assert client.get("/v1/invoices", headers=theirs).json() == []
    assert client.get(f"/v1/invoices/{invoice_id}", headers=theirs).status_code == 404
    r = client.post("/v1/engines/deadline/run", headers=theirs,
                    json={"invoice_id": invoice_id, "inputs": {"delivery": "2026-08-01"}})
    assert r.status_code == 404


def test_engine_run_through_api_is_stored(client, dsn):
    h = login(client, "agent@lender-a.example")
    invoice_id = seeded_invoice_id(client, h)
    inputs = {"delivery": "2026-08-01", "written_days": 45}
    r = client.post("/v1/engines/deadline/run", headers=h,
                    json={"invoice_id": invoice_id, "inputs": inputs})
    assert r.status_code == 200
    direct = deadline.run(inputs)
    assert r.json()["result"] == direct["result"]
    with psycopg.connect(dsn) as c:
        rows = c.execute("SELECT rule_version, inputs_hash, inputs, outputs FROM engine_run "
                         "WHERE engine='deadline' AND inputs = %s::jsonb",
                         ('{"delivery":"2026-08-01","written_days":45}',)).fetchall()
    assert rows and rows[0][0] == direct["rule_version"] and rows[0][1] == direct["input_hash"]
    assert rows[0][2] == inputs and rows[0][3]["result"] == direct["result"]


def test_unknown_engine_is_404(client):
    h = login(client, "agent@lender-a.example")
    r = client.post("/v1/engines/nope/run", headers=h, json={"inputs": {}})
    assert r.status_code == 404


def test_reading_stores_engine_runs_once(client, dsn):
    h = login(client)
    read(client, h)
    read(client, h)
    with psycopg.connect(dsn) as c:
        n = dict(c.execute("SELECT engine, count(*) FROM engine_run GROUP BY engine").fetchall())
    assert n == {"deadline": 1, "eligibility": 1, "interest": 1, "evidence": 1, "collateral": 1}


def test_only_approved_bank_rates_reach_the_interest_engine(client, dsn):
    with psycopg.connect(dsn, autocommit=True) as c:  # an unapproved 9% row must be ignored
        c.execute("INSERT INTO bank_rate (effective_from, rate, source_url) "
                  "VALUES ('2026-10-20', 9, 'https://example.invalid/pending')")
    body = read(client, login(client)).json()
    want = interest_run({"principal": "1000000.00", "interest_start": "2026-09-16",
                         "as_of": AS_OF, "bank_rates": RATES})["result"]["claim_display"]
    assert body["claim"]["claim_value"] == want


def test_seeded_bank_rates_carry_a_source_and_two_people(dsn):
    with psycopg.connect(dsn) as c:
        rows = c.execute("SELECT effective_from::text, rate::text, source_url, "
                         "entered_by <> approved_by FROM bank_rate ORDER BY 1").fetchall()
    assert [r[:2] for r in rows] == [("2025-12-05", "5.500000"), ("2026-10-07", "5.750000")]
    assert all(r[2].startswith("https://") and r[3] for r in rows)
