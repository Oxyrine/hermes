"""Ticket 16: fixture adapters, loading and matching, through the API."""

import json

import psycopg
import pytest
from fastapi.testclient import TestClient

from hermes.api import create_app
from hermes.dispatcher import drain
from hermes.ledger import db, ingest, load
from hermes.synthetic import generate
from test_seeded_invoice_api import SECRET, login


@pytest.fixture(scope="module")
def root(tmp_path_factory):
    path = tmp_path_factory.mktemp("syn")
    return path, generate(path, seed=42)


@pytest.fixture
def world(_server_url, root, monkeypatch):
    """The synthetic set loaded up to the pulls: suppliers, consents and invoices, nothing fetched."""
    monkeypatch.setenv("HERMES_FIXTURES", str(root[0]))
    with psycopg.connect(_server_url, autocommit=True) as c:
        db.reset(c)
        load.run(c, root[0], pull=False)
    return _server_url


@pytest.fixture
def client(world):
    return TestClient(create_app(world, secret=SECRET, env="development"))


@pytest.fixture
def conn(world):
    with psycopg.connect(world, autocommit=True) as c:
        yield c


def pull(client, conn, root, sid, source, **body):
    gstin = next(s["gstin"] for s in root[1]["suppliers"] if s["id"] == sid)
    row = conn.execute("SELECT id::text FROM supplier WHERE gstin=%s", (gstin,)).fetchone()
    return client.post(f"/v1/suppliers/{row[0]}/pulls", headers=login(client),
                       json={"source": source} | body)


def invoice_id(client, root, inv):
    no = next(i["invoice_no"] for i in root[1]["invoices"] if i["id"] == inv)
    return next(i["id"] for i in client.get("/v1/invoices", headers=login(client)).json()
                if i["invoice_no"] == no)


def test_load_command_loads_the_whole_synthetic_set(_server_url, root):
    with psycopg.connect(_server_url, autocommit=True) as c:
        db.reset(c)
        out = load.run(c, root[0])
        assert out["suppliers"] == 3 and out["buyers"] == 4 and out["invoices"] == 30
        assert c.execute("SELECT count(*) FROM invoice").fetchone()[0] == 30
        assert c.execute("SELECT count(*) FROM invoice WHERE state='verified'").fetchone()[0] == 30
        assert c.execute("SELECT count(*) FROM invoice WHERE due_date IS NULL").fetchone()[0] == 0
        before = c.execute("SELECT count(*) FROM raw_record").fetchone()[0]
        tenant, sup = c.execute("SELECT tenant_id, id FROM supplier LIMIT 1").fetchone()
        ingest.pull(c, tenant, sup, {"source": "documents"}, root[0])  # a second pull adds nothing
        assert c.execute("SELECT count(*) FROM raw_record").fetchone()[0] == before


def test_exact_match_links_stores_raw_unchanged_and_routes_an_event(client, conn, root):
    r = pull(client, conn, root, "S1", "ims_supplier_view")
    assert r.status_code == 200, r.text
    assert r.json()["linked"] == r.json()["fetched"] > 0 and r.json()["review"] == 0
    inv = invoice_id(client, root, "INV-001")
    raw = conn.execute("SELECT payload, source, external_id, consent_id IS NOT NULL FROM raw_record "
                       "WHERE payload->>'inum'=%s", ("S1/26-27/0001",)).fetchone()
    fixture = json.loads((root[0] / "gst/ims_supplier_view.json").read_text())
    entry = next(i for s in fixture for b in s["b2b"] for i in b["inv"] if i["inum"] == "S1/26-27/0001")
    assert {k: raw[0][k] for k in entry} == entry  # the fixture's record, unedited
    assert raw[1:] == ("ims_supplier_view", "S1/26-27/0001", True)
    assert conn.execute("SELECT kind FROM event_queue WHERE invoice_id=%s", (inv,)).fetchall() == [
        ("ims.action_changed",)]
    assert conn.execute("SELECT action, raw_ref IS NOT NULL FROM ims_event WHERE invoice_id=%s",
                        (inv,)).fetchall() == [("accepted", True)]
    with pytest.raises(psycopg.Error):  # raw records are never edited
        conn.execute("UPDATE raw_record SET payload='{}'")
    assert pull(client, conn, root, "S1", "ims_supplier_view").json()["duplicate"] == r.json()["fetched"]


def test_missing_or_withdrawn_consent_refuses_the_fetch(client, conn, root):
    sid = conn.execute("SELECT id::text FROM supplier WHERE legal_name LIKE 'Sundaram%'").fetchone()[0]
    h = login(client, "supplier@sundaram.example")
    consent = next(c for c in client.get(f"/v1/suppliers/{sid}/consents", headers=h).json()
                   if c["source"] == "bank_statement")
    assert client.post(f"/v1/suppliers/{sid}/consents/{consent['id']}/withdraw",
                       headers=h).status_code == 200
    r = pull(client, conn, root, "S2", "bank_statement")
    assert r.status_code == 409 and "consent" in r.json()["detail"]
    assert pull(client, conn, root, "S2", "bank_statement", purpose="underwriting").status_code == 409
    assert conn.execute("SELECT count(*) FROM raw_record").fetchone()[0] == 0


def test_partial_match_goes_to_review_and_links_nothing(client, conn, root):
    pull(client, conn, root, "S3", "documents")
    r = pull(client, conn, root, "S3", "bank_statement")  # part payments name no invoice
    assert r.status_code == 200 and r.json()["review"] == 2 and r.json()["linked"] == 1  # one full payment
    assert conn.execute("SELECT count(*) FROM payment").fetchone()[0] == 1
    a, _ = client.get("/v1/actions", headers=login(client, "supplier@nila.example"),
                      params={"status": "proposed"}).json()  # the supplier confirms a link
    assert a["kind"] == "doc_link" and a["draft"]["source"] == "bank_statement"
    assert a["draft"]["score"] == 0.5 and len(a["draft"]["candidates"]) > 1


def test_a_record_that_disagrees_with_the_invoice_is_reviewed_not_linked(client, conn, root):
    pull(client, conn, root, "S1", "documents")
    conn.execute("UPDATE invoice SET irn='not-the-qr-irn' WHERE invoice_no='S1/26-27/0001'")
    r = pull(client, conn, root, "S1", "einvoice")
    assert r.json()["review"] == 1 and r.json()["linked"] == r.json()["fetched"] - 1
    inv = invoice_id(client, root, "INV-001")
    assert conn.execute("SELECT count(*) FROM evidence_item WHERE invoice_id=%s AND "
                        "signal='irn_valid_matching'", (inv,)).fetchone()[0] == 0
    assert "IRN" in client.get("/v1/actions", headers=login(client, "supplier@kaveri.example")).json()[0][
        "draft"]["reason"]


def test_qr_is_decoded_and_its_irn_checked_against_the_invoice(client, conn, root):
    pull(client, conn, root, "S1", "documents")
    assert pull(client, conn, root, "S1", "einvoice").json()["review"] == 0
    inv = invoice_id(client, root, "INV-001")
    irn = next(i["irn"] for i in root[1]["invoices"] if i["id"] == "INV-001")
    assert conn.execute("SELECT irn FROM invoice WHERE id=%s", (inv,)).fetchone()[0] == irn
    ev = client.get(f"/v1/invoices/{inv}", headers=login(client)).json()["evidence"]
    assert "irn_valid_matching" in [c["signal"] for c in ev["contributions"]]


def test_ims_change_is_a_new_row_and_reruns_evidence_and_collateral(client, conn, root):
    for src in ("documents", "einvoice", "ims_supplier_view"):
        pull(client, conn, root, "S1", src)
    inv = invoice_id(client, root, "INV-019")  # the reversal scenario: accepted, later rejected
    h = login(client)
    assert client.get(f"/v1/invoices/{inv}", headers=h).json()["evidence"]["hard_flags"] == []
    pull(client, conn, root, "S1", "ims_supplier_view", fixture="ims_supplier_view_reversal")
    assert conn.execute("SELECT action FROM ims_event WHERE invoice_id=%s ORDER BY id",
                        (inv,)).fetchall() == [("accepted",), ("rejected",)]
    with pytest.raises(psycopg.Error):
        conn.execute("DELETE FROM ims_event")
    runs = conn.execute("SELECT count(*) FROM engine_run WHERE invoice_id=%s", (inv,)).fetchone()[0]
    assert drain(conn.info.dsn, SECRET, client) > 0  # the agent re-reads on ims.action_changed
    assert conn.execute("SELECT count(*) FROM engine_run WHERE invoice_id=%s", (inv,)).fetchone()[0] > runs
    assert client.get(f"/v1/invoices/{inv}", headers=h).json()["evidence"]["hard_flags"] == ["ims_rejected"]


def test_bank_credit_becomes_a_payment_and_the_invoice_moves_to_paid(client, conn, root):
    for src in ("documents", "einvoice", "ims_supplier_view", "bank_statement"):
        pull(client, conn, root, "S1", src)
    inv = invoice_id(client, root, "INV-001")  # a clean-path invoice paid in full
    h = login(client)
    (receipt,) = client.get(f"/v1/invoices/{inv}/receipts", headers=h).json()
    assert receipt["amount"] == "364523.24" and receipt["source"] == "bank_statement"
    assert conn.execute("SELECT raw_id IS NOT NULL FROM payment").fetchone()[0]
    assert drain(conn.info.dsn, SECRET, client) > 0
    assert client.get(f"/v1/invoices/{inv}", headers=h).json()["state"] == "paid"
