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


def upload(client, h, data=PDF, ctype="application/pdf", **q):
    q = {"filename": "gst.pdf", "doc_type": "certificate"} | q
    return client.post("/v1/documents", params=q, content=data,
                       headers=h | {"Content-Type": ctype})


def test_refused_file_types_and_sizes(client, db):
    h = supplier_login(client)
    for data, ctype in [(b"MZ\x90\x00", "application/x-msdownload"),   # not an allowed type
                        (b"<script>alert(1)</script>", "application/pdf"),  # mislabelled
                        (PDF, "image/png"), (b"", "application/pdf"),
                        (b"%PDF-" + b"0" * (5 * 1024 * 1024), "application/pdf")]:
        r = upload(client, h, data, ctype)
        assert r.status_code in (413, 422), (ctype, r.text)
    assert db.execute("SELECT count(*) FROM document WHERE filename='gst.pdf'").fetchone()[0] == 0


def test_upload_stores_bytes_unchanged_publishes_event_and_is_never_public(client, db):
    h = supplier_login(client)
    inv = client.get("/v1/invoices", headers=h).json()[0]["id"]
    r = upload(client, h, doc_type="po", invoice_id=inv)
    assert r.status_code == 200, r.text
    import hashlib
    assert r.json()["sha256"] == hashlib.sha256(PDF).hexdigest() and r.json()["invoice_id"] == inv
    assert bytes(db.execute("SELECT content FROM document WHERE id=%s", (r.json()["id"],)
                            ).fetchone()[0]) == PDF
    assert db.execute("SELECT invoice_id::text, payload->>'document_id' FROM event_queue "
                      "WHERE kind='document.ingested'").fetchone() == (inv, r.json()["id"])
    url = f"/v1/documents/{r.json()['id']}/content"
    assert client.get(url).status_code == 401
    got = client.get(url, headers=h)
    assert got.content == PDF and got.headers["content-type"] == "application/pdf"
    other = onboard(client).json()["id"]
    pinned = upload(client, h, supplier_id=other)  # a supplier is pinned to their own supplier
    assert pinned.status_code == 200 and pinned.json()["supplier_id"] != other


def test_supplier_level_document_and_scoping(client, db):
    sid, h = seeded_supplier_id(db), supplier_login(client)
    r = upload(client, h, supplier_id=sid)
    assert r.status_code == 200 and r.json()["invoice_id"] is None and r.json()["supplier_id"] == sid
    assert upload(client, h, doc_type="po").status_code == 422  # invoice documents need an invoice
