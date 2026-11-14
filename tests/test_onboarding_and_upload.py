"""Ticket 15: onboarding, consent, invoice creation and document upload through the API."""


import psycopg
import pytest
from fastapi.testclient import TestClient

from hermes.api import create_app
from hermes.synthetic.gstin import gstin_checksum
from test_seeded_invoice_api import SECRET, login

PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"


@pytest.fixture
def client(dsn):
    return TestClient(create_app(dsn, secret=SECRET, env="development"))


@pytest.fixture
def db(dsn):
    with psycopg.connect(dsn, autocommit=True) as c:
        yield c


def gstin(first14="27AABCN0003C1Z"):
    return first14 + gstin_checksum(first14)


SUPPLIER = {
    "gstin": gstin(), "legal_name": "Nashik Components (synthetic)",
    "udyam_urn": "UDYAM-MH-26-0001234", "udyam_reg_date": "2022-04-01",
    "enterprise_type": "manufacturing", "classifications": {"2025-26": "micro", "2026-27": "small"},
}


def onboard(client, **over):
    return client.post("/v1/suppliers", headers=login(client), json=SUPPLIER | over)


def test_bad_gstin_is_refused_with_a_clear_message(client):
    r = onboard(client, gstin=SUPPLIER["gstin"][:-1] + "0")
    assert r.status_code == 422
    assert "GSTIN" in r.json()["detail"] and "checksum" in r.json()["detail"]


def test_onboarding_stores_udyam_details_and_per_year_classification(client, db):
    r = onboard(client)
    assert r.status_code == 200, r.text
    row = db.execute("SELECT udyam_urn, udyam_reg_date::text, enterprise_type, onboarded_at IS NOT NULL "
                     "FROM supplier WHERE id=%s", (r.json()["id"],)).fetchone()
    assert row == ("UDYAM-MH-26-0001234", "2022-04-01", "manufacturing", True)
    assert db.execute("SELECT fy, class FROM udyam_classification WHERE supplier_id=%s ORDER BY fy",
                      (r.json()["id"],)).fetchall() == [("2025-26", "micro"), ("2026-27", "small")]


def supplier_login(client):
    return login(client, "supplier@sundaram.example")


def seeded_supplier_id(db):
    return db.execute("SELECT id::text FROM supplier").fetchone()[0]


def test_consent_names_source_purpose_lender_and_expiry_and_can_be_withdrawn(client, db):
    sid, h = seeded_supplier_id(db), supplier_login(client)
    body = {"source": "gstr1", "purpose": "underwriting", "expires_at": "2099-11-14"}
    r = client.post(f"/v1/suppliers/{sid}/consents", headers=h, json=body)
    assert r.status_code == 200, r.text
    assert r.json()["lender"] == "Lender A (synthetic)" and r.json()["withdrawn_at"] is None
    w = client.post(f"/v1/suppliers/{sid}/consents/{r.json()['id']}/withdraw", headers=h)
    assert w.status_code == 200 and w.json()["withdrawn_at"] is not None
    listed = client.get(f"/v1/suppliers/{sid}/consents", headers=h).json()
    assert [(x["source"], x["purpose"], x["expires_at"]) for x in listed] == [
        ("gstr1", "underwriting", "2099-11-14")]
    bad = client.post(f"/v1/suppliers/{sid}/consents", headers=h, json=body | {"source": "diary"})
    assert bad.status_code == 422 and "source" in bad.json()["detail"]
    past = client.post(f"/v1/suppliers/{sid}/consents", headers=h,
                       json=body | {"expires_at": "2020-01-01"})
    assert past.status_code == 422


def test_a_supplier_cannot_consent_for_another_supplier(client, db):
    other = onboard(client).json()["id"]
    r = client.post(f"/v1/suppliers/{other}/consents", headers=supplier_login(client),
                    json={"source": "gstr1", "purpose": "underwriting", "expires_at": "2099-11-14"})
    assert r.status_code == 404


INVOICE = {"invoice_no": "SF/2026/0099", "buyer_gstin": gstin("29AABCM0001B1Z"),
           "invoice_date": "2026-10-01", "total": "118000.00"}


def test_invoice_starts_ingested_and_duplicate_number_is_refused(client, db):
    h = supplier_login(client)
    r = client.post("/v1/invoices", headers=h, json=INVOICE)
    assert r.status_code == 200, r.text
    assert r.json()["state"] == "ingested"
    dup = client.post("/v1/invoices", headers=h, json=INVOICE)
    assert dup.status_code == 409 and "already exists" in dup.json()["detail"]
    odd = INVOICE | {"invoice_no": "X", "total": "1e3"}
    assert client.post("/v1/invoices", headers=h, json=odd).status_code == 422
    unknown = INVOICE | {"invoice_no": "Y", "buyer_gstin": gstin("29AABCZ9999B1Z")}
    assert client.post("/v1/invoices", headers=h, json=unknown).status_code == 422
