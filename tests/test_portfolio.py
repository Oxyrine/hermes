"""Ticket 25: portfolio, buyer view, watchlist and alerts, through the API."""

import csv
import io

import psycopg
import pytest
from fastapi.testclient import TestClient

from hermes.api import create_app
from hermes.synthetic.gstin import gstin_checksum
from test_seeded_invoice_api import AS_OF, SECRET, login, read, seeded_invoice_id


@pytest.fixture
def client(dsn):
    return TestClient(create_app(dsn, secret=SECRET, env="development"))


@pytest.fixture
def db(dsn):
    with psycopg.connect(dsn, autocommit=True) as c:
        yield c


def book(client, h, **params):
    r = client.get("/v1/portfolio", params={"as_of": AS_OF, **params}, headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def second_buyer_invoice(db, state="overdue"):
    """A copy of the seeded invoice, billed to a new buyer, with no evidence (so band D)."""
    g = "29AABCZ0009Z1Z"
    buyer = db.execute("INSERT INTO buyer (gstin, legal_name) VALUES (%s,'Zenith Buyer (synthetic)') "
                       "RETURNING id", (g + gstin_checksum(g),)).fetchone()[0]
    inv = db.execute(
        "INSERT INTO invoice (tenant_id, supplier_id, buyer_id, contract_id, invoice_no, invoice_date, "
        "total, state, due_date) SELECT tenant_id, supplier_id, %s, contract_id, 'AC/2026/0999', "
        "invoice_date, 500000, %s, due_date FROM invoice RETURNING id", (buyer, state)).fetchone()[0]
    db.execute("INSERT INTO document (tenant_id, invoice_id, supplier_id, doc_type, extracted) "
               "SELECT tenant_id, %s, supplier_id, 'grn', extracted FROM document WHERE doc_type='grn'",
               (inv,))
    return buyer, inv


def test_portfolio_row_carries_the_columns_and_matches_the_invoice_read(client):
    h = login(client)
    (row,) = book(client, h)
    v = read(client, h).json()
    assert row["id"] == v["id"] and row["total"] == v["total"] and row["state"] == v["state"]
    assert row["band"] == v["evidence"]["band"] and row["days_late"] == 60
    assert row["claim_value"] == v["claim"]["claim_value"]
    assert row["exposure"] == v["collateral"]["exposure"] and row["ltv"] == v["collateral"]["ltv"]
    assert row["supplier"].startswith("Sundaram") and row["buyer"].startswith("Meridian")
    assert row["watchlist"] is False and row["alerts"] == []


def test_portfolio_is_tenant_scoped_and_honours_each_filter(client, db):
    h = login(client)
    buyer2, _ = second_buyer_invoice(db)
    assert len(book(client, h)) == 2
    first = next(r for r in book(client, h) if r["invoice_no"] != "AC/2026/0999")
    assert [r["invoice_no"] for r in book(client, h, state="verified")] == [first["invoice_no"]]
    assert [r["invoice_no"] for r in book(client, h, state="overdue")] == ["AC/2026/0999"]
    assert [r["invoice_no"] for r in book(client, h, band="D")] == ["AC/2026/0999"]
    assert [r["invoice_no"] for r in book(client, h, band=first["band"])] == [first["invoice_no"]]
    assert [r["invoice_no"] for r in book(client, h, buyer=str(buyer2))] == ["AC/2026/0999"]
    assert book(client, h, state="verified", band="D") == []
    # a second lender sees none of this
    t2 = db.execute("INSERT INTO tenant (name, kind, max_ltv, lender_rate_nominal) "
                    "VALUES ('Lender B','bank',0.8,12) RETURNING id").fetchone()[0]
    db.execute("INSERT INTO app_user (tenant_id, email, role) VALUES (%s,'ops@lender-b.example','lender_ops')", (t2,))
    hb = login(client, "ops@lender-b.example")
    assert book(client, hb) == []
    assert client.get(f"/v1/buyers/{buyer2}", params={"as_of": AS_OF}, headers=hb).status_code == 404
    assert client.get("/v1/portfolio").status_code == 401
    assert client.get("/v1/portfolio", headers=login(client, "supplier@sundaram.example")).status_code == 403


def test_csv_export_has_the_same_figures_as_the_table(client, db):
    h = login(client)
    second_buyer_invoice(db)
    rows = book(client, h, band="D")
    r = client.get("/v1/portfolio.csv", params={"as_of": AS_OF, "band": "D"}, headers=h)
    assert r.headers["content-type"].startswith("text/csv")
    got = list(csv.DictReader(io.StringIO(r.text)))
    assert len(got) == len(rows) == 1
    for k in ("supplier", "buyer", "total", "state", "band", "days_late", "claim_value", "exposure", "ltv"):
        assert got[0][k] == ("" if rows[0][k] is None else str(rows[0][k]))


def test_interest_figures_are_hidden_when_ineligible(client, db):
    h = login(client)
    assert book(client, h)[0]["claim_value"] is not None
    db.execute("UPDATE udyam_classification SET class='medium'")
    (row,) = book(client, h)
    assert row["eligibility"] == "ineligible" and row["claim_value"] is None


def test_buyer_view_computes_share_accepted_and_average_days_late(client, db):
    h = login(client)
    buyer, _ = second_buyer_invoice(db)
    db.execute("UPDATE invoice SET buyer_id=%s WHERE invoice_no='AC/2026/0412'", (buyer,))
    v = client.get(f"/v1/buyers/{buyer}", params={"as_of": AS_OF}, headers=h).json()
    assert v["buyer"].startswith("Zenith") and len(v["invoices"]) == 2
    assert v["share_accepted"] == "0.50"   # the seeded invoice has ims_accepted, the copy has none
    assert v["average_days_late"] == "60.0"


def test_watchlist_mark_shows_in_the_portfolio_and_comes_off(client, db):
    h = login(client)
    buyer = db.execute("SELECT buyer_id FROM invoice").fetchone()[0]
    assert client.put(f"/v1/buyers/{buyer}/watchlist", headers=h).status_code == 200
    assert book(client, h)[0]["watchlist"] is True
    assert client.get(f"/v1/buyers/{buyer}", params={"as_of": AS_OF}, headers=h).json()["watchlist"] is True
    assert client.delete(f"/v1/buyers/{buyer}/watchlist", headers=h).status_code == 200
    assert book(client, h)[0]["watchlist"] is False


def alerts(client, h, as_of=AS_OF):
    return client.get("/v1/alerts", params={"as_of": as_of}, headers=h).json()


def test_alerts_cover_hard_flags_ltv_breaches_and_rate_changes_and_can_be_worked(client, db):
    h = login(client)
    inv = seeded_invoice_id(client, h)
    assert alerts(client, h) == []
    db.execute("INSERT INTO evidence_item (tenant_id, invoice_id, signal, source_ref, detected_at) "
               "SELECT tenant_id, id, 'ims_rejected', '{}', now() FROM invoice")
    got = alerts(client, h, "2026-10-20")
    assert {a["kind"] for a in got} == {"hard_flag", "bank_rate_change"}
    flag = next(a for a in got if a["kind"] == "hard_flag")
    assert flag["invoice_id"] == inv and book(client, h, as_of="2026-10-20")[0]["alerts"] == ["hard_flag"]
    assert client.post("/v1/alerts/acknowledge", json={"key": flag["key"]}, headers=h).status_code == 200
    assign = {"key": flag["key"], "assignee": "approver@lender-a.example"}
    assert client.post("/v1/alerts/assign", json=assign, headers=h).status_code == 200
    after = next(a for a in alerts(client, h, "2026-10-20") if a["key"] == flag["key"])
    assert after["acknowledged_by"] == "ops@lender-a.example"
    assert after["assigned_to"] == "approver@lender-a.example"
    assert client.post("/v1/alerts/acknowledge", json={"key": "hard_flag:nope"}, headers=h).status_code == 404
    assert client.post("/v1/alerts/assign", json=assign | {"assignee": "x@nowhere"}, headers=h).status_code == 422
    # an LTV breach: a funded advance far above the band limit
    db.execute("INSERT INTO advance (tenant_id, invoice_id, principal, nominal_rate, disbursed_on, status) "
               "SELECT tenant_id, id, 990000, 18, '2026-09-01', 'open' FROM invoice")
    assert "ltv_breach" in {a["kind"] for a in alerts(client, h)}
