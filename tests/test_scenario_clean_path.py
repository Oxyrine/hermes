"""Ticket 19: scenario 1, the clean path, from upload to closed. API, fixture pulls, the clock and
approval calls, the scripted runner and the fake model only."""

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from hermes.api import create_app
from test_adapters import conn, invoice_id, pull, root, world  # noqa: F401
from test_classify_extract import fake_for, reader_for, run, state, upload
from test_seeded_invoice_api import SECRET, login


@pytest.fixture
def client(world):  # noqa: F811
    return TestClient(create_app(world, secret=SECRET, env="development"))


def test_clean_path_from_upload_to_closed(client, conn, root):  # noqa: F811
    inv = root[1]["e2e_scenarios"]["1_clean_path"][0]
    sid = next(i["supplier"] for i in root[1]["invoices"] if i["id"] == inv)
    h = login(client)
    for src in ("einvoice", "ewb", "gstr1", "ims_supplier_view"):
        assert pull(client, conn, root, sid, src).status_code == 200
    iid = upload(client, root, inv)
    run(client, conn, reader_for(root, fake_for(root, inv)))

    view = client.get(f"/v1/invoices/{iid}", headers=h).json()
    assert view["evidence"]["score"] >= 80 and view["evidence"]["band"] == "A"
    assert view["hard_flags"] == []
    assert state(client, iid) == "financeable"
    assert view["collateral"]["advance_rate"] == "0.80"
    offer = (Decimal(view["total"]) * Decimal("0.8")).quantize(Decimal("0.01"))

    assert client.post(f"/v1/invoices/{iid}/advances", headers=h, json={
        "principal": str(offer), "disbursed_on": "2026-09-01"}).status_code == 200
    assert state(client, iid) == "advanced"
    due = view["deadline"]["due"]
    client.put("/dev/clock", json={"date": due})  # on the due date: not late
    assert client.post("/dev/payments", headers=h, json={
        "invoice_id": iid, "amount": view["total"], "utr": "UTR-CLEAN"}).status_code == 200
    run(client, conn, None)
    assert state(client, iid) == "paid"
    after = client.get(f"/v1/invoices/{iid}", headers=h).json()
    assert Decimal(after["claim"]["interest"]) == 0
    w = after["waterfall"]
    assert Decimal(w["receipts"]) == Decimal(view["total"]) and Decimal(w["supplier"]) > 0
    assert client.post(f"/v1/invoices/{iid}/lender-confirm", headers=h).status_code == 200
    assert state(client, iid) == "closed"
