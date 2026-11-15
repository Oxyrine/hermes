"""Ticket 30: GSTR-1A correction draft (scenario 2), through ingest, the dispatcher and the API."""

import json

import pytest
from fastapi.testclient import TestClient

from hermes.api import create_app
from hermes.dispatcher import drain
from test_adapters import conn, invoice_id, pull, root, world  # noqa: F401
from test_seeded_invoice_api import SECRET, login

EMAIL = {"S1": "supplier@kaveri.example", "S2": "supplier@sundaram.example",
         "S3": "supplier@nila.example"}


@pytest.fixture
def client(world):  # noqa: F811
    return TestClient(create_app(world, secret=SECRET, env="development"))


def drafts(client, email, iid=None):
    acts = client.get("/v1/actions", headers=login(client, email), params={"status": "proposed"}).json()
    return [a for a in acts if a["kind"] == "gstr1a_draft" and iid in (None, a["invoice_id"])]


def state(client, inv):
    return client.get(f"/v1/invoices/{inv}", headers=login(client)).json()["state"]


def ims_fixture(root, name, inum, action, **extra):  # noqa: F811
    inv = next(i for i in root[1]["invoices"] if i["invoice_no"] == inum)
    buyer = inv["buyer"]
    d = json.loads((root[0] / f"docs/{inv['id']}/invoice.truth.json").read_text())["invoice_date"]
    rec = {"inum": inum, "idt": f"{d[8:]}-{d[5:7]}-{d[:4]}", "val": inv["total"], "action": action,
           "gstr2b_gendt": "14-02-2026"} | extra
    gstin = next(s["gstin"] for s in root[1]["suppliers"] if s["id"] == inv["supplier"])
    ctin = next(b["gstin"] for b in root[1]["buyers"] if b["id"] == buyer)
    (root[0] / f"gst/{name}.json").write_text(json.dumps(
        [{"gstin": gstin, "rtnprd": "012026", "b2b": [{"ctin": ctin, "inv": [rec]}]}]))


def verify_all(client, conn, root, sid):  # noqa: F811
    """What the loader does: pull the evidence, then move matched invoices to verified."""
    for src in ("documents", "einvoice"):
        pull(client, conn, root, sid, src)
    for i in client.get("/v1/invoices", headers=login(client)).json():
        client.post(f"/v1/invoices/{i['id']}/state", headers=login(client, "agent@lender-a.example"), json={"to": "verified"})


def blocked_invoice(client, conn, root):  # noqa: F811
    """Scenario 2: the first gst_block invoice, its supplier's GSTR-1 pulled and the agent run."""
    inv = next(i for i in root[1]["invoices"] if i["id"] == root[1]["e2e_scenarios"]["2_gst_block"][0])
    verify_all(client, conn, root, inv["supplier"])
    for src in ("ims_supplier_view", "gstr1"):
        pull(client, conn, root, inv["supplier"], src)
    assert drain(conn.info.dsn, SECRET, client) > 0
    return inv, invoice_id(client, root, inv["id"])


def test_b2c_filing_blocks_the_invoice_and_drafts_a_correction_for_the_supplier(client, conn, root):  # noqa: F811
    inv, iid = blocked_invoice(client, conn, root)
    assert state(client, iid) == "gst_blocked"
    (a,) = drafts(client, EMAIL[inv["supplier"]], iid)
    d = a["draft"]
    assert a["kind"] == "gstr1a_draft" and a["invoice_id"] == iid and a["needs"] == ["supplier"]
    assert d["filed"]["table"] == "B2CL" and d["should_have_been"]["table"] == "B2B"
    assert d["should_have_been"]["buyer_gstin"] == next(
        b["gstin"] for b in root[1]["buyers"] if b["id"] == inv["buyer"])
    assert len(d["steps"]) >= 3 and "accountant" in d["note"] and "Hermes files nothing" in d["note"]
    assert "Rule 59" in d["rule"] and "legal advice" in d["note"]
    drain(conn.info.dsn, SECRET, client)
    assert len(drafts(client, EMAIL[inv["supplier"]], iid)) == 1  # no second draft
    other = [i for i in root[1]["invoices"] if i["scenario"] != "gst_block"
             and i["supplier"] == inv["supplier"]]
    assert state(client, invoice_id(client, root, other[0]["id"])) == "verified"  # B2B filings untouched


def test_supplier_dismisses_or_approves_and_nothing_is_filed(client, conn, root):  # noqa: F811
    inv, iid = blocked_invoice(client, conn, root)
    h = login(client, EMAIL[inv["supplier"]])
    (a,) = drafts(client, EMAIL[inv["supplier"]], iid)
    r = client.post(f"/v1/actions/{a['id']}/approve", headers=h)
    assert r.status_code == 200 and r.json()["status"] == "approved"
    assert state(client, iid) == "gst_blocked"  # approval files nothing and moves nothing
    drain(conn.info.dsn, SECRET, client)
    assert state(client, iid) == "gst_blocked"


def test_accepted_corrected_record_returns_to_verified_then_financeable_under_the_guard(client, conn, root):  # noqa: F811
    inv, iid = blocked_invoice(client, conn, root)
    ims_fixture(root, "ims_corrected", inv["invoice_no"], "A", actndt="20-01-2026")
    pull(client, conn, root, inv["supplier"], "ims_supplier_view", fixture="ims_corrected")
    drain(conn.info.dsn, SECRET, client)
    view = client.get(f"/v1/invoices/{iid}", headers=login(client)).json()
    assert view["state"] == ("financeable" if view["evidence"]["band"] in "ABC" and
                             view["eligibility"]["status"] != "ineligible" else "verified")
    assert view["state"] in ("verified", "financeable")


def test_ims_rejection_with_a_supplier_side_fix_blocks_but_a_buyer_dispute_does_not(client, conn, root):  # noqa: F811
    fixable, dispute = [i["invoice_no"] for i in root[1]["invoices"]
                        if i["supplier"] == "S1" and i["scenario"] == "clean_path"][:2]
    ims_fixture(root, "ims_fix", fixable, "R", reason_code="invoice_details_mismatch")
    ims_fixture(root, "ims_dispute", dispute, "R")
    verify_all(client, conn, root, "S1")
    pull(client, conn, root, "S1", "ims_supplier_view", fixture="ims_fix")
    pull(client, conn, root, "S1", "ims_supplier_view", fixture="ims_dispute")
    drain(conn.info.dsn, SECRET, client)
    by_no = {i["invoice_no"]: i["id"] for i in client.get("/v1/invoices", headers=login(client)).json()}
    assert state(client, by_no[fixable]) == "gst_blocked"
    assert state(client, by_no[dispute]) == "verified"
    (a,) = drafts(client, EMAIL["S1"])
    assert a["kind"] == "gstr1a_draft" and a["draft"]["filed"]["ims_action"] == "rejected"
