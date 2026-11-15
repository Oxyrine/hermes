"""Ticket 18: classify and extract, on the fake model. No key, no network."""

import json
from copy import deepcopy

import pytest
from fastapi.testclient import TestClient

from hermes.api import create_app
from hermes.dispatcher import drain
from hermes.extraction import Reader, check_fields, pdf_text, three_way
from hermes.llm import Document, FakeModel, MemoryCache, ModelClient, synthetic_hashes
from test_adapters import conn, invoice_id, pull, root, world  # noqa: F401
from test_seeded_invoice_api import SECRET, login

LITE, FLASH = "gemini-3.5-flash-lite", "gemini-3.8-flash"
TYPE = {"invoice": "invoice", "po": "purchase_order", "grn": "goods_receipt_note"}


@pytest.fixture
def client(world):  # noqa: F811
    return TestClient(create_app(world, secret=SECRET, env="development"))


def truth_of(root, inv, kind):  # noqa: F811
    return json.loads((root[0] / f"docs/{inv}/{kind}.truth.json").read_text())


def pdf_of(root, inv, kind):  # noqa: F811
    return (root[0] / f"docs/{inv}/{kind}.pdf").read_bytes()


def fake_for(root, inv, edits=None, kinds=("invoice", "po", "grn")):  # noqa: F811
    """Ground truth by document hash, as a model that reads perfectly (plus any edits)."""
    truth = {}
    for k in kinds:
        t = truth_of(root, inv, k) | {"confidence": 0.97} | (edits or {}).get(k, {})
        t.pop("injection", None)
        h = Document(pdf_of(root, inv, k)).sha256
        truth[("classify", h)] = {"doc_type": TYPE[k], "confidence": 0.95}
        truth[("extract", h)] = t
        truth[("mismatch_note", h)] = {"note": "The quantity on this document differs from the invoice."}
    return FakeModel(truth)


def reader_for(root, model, cache=None):  # noqa: F811
    return Reader(ModelClient(model, cache=cache, manifest_hashes=synthetic_hashes(root[1])))


def clean_scenario(root):  # noqa: F811
    return root[1]["e2e_scenarios"]["1_clean_path"][0] if "1_clean_path" in root[1]["e2e_scenarios"] \
        else next(iter(root[1]["e2e_scenarios"].values()))[0]


def upload(client, root, inv, kinds=("invoice", "po", "grn")):  # noqa: F811
    h = login(client)
    iid = invoice_id(client, root, inv)
    for k in kinds:
        r = client.post("/v1/documents", params={"filename": f"{k}.pdf", "doc_type": k,
                                                 "invoice_id": iid},
                        content=pdf_of(root, inv, k), headers=h | {"Content-Type": "application/pdf"})
        assert r.status_code == 200, r.text
    return iid


def prepare(client, conn, root, inv_id, fixture=None):  # noqa: F811
    """The GSTR-1 and e-invoice records pulled for the invoice's supplier."""
    sid = next(i["supplier"] for i in root[1]["invoices"] if i["id"] == inv_id)
    pull(client, conn, root, sid, "einvoice")
    pull(client, conn, root, sid, "gstr1", **({"fixture": fixture} if fixture else {}))


def run(client, conn, reader):  # noqa: F811
    drain(conn.info.dsn, SECRET, client, reader)


def state(client, iid):
    rows = client.get("/v1/invoices", headers=login(client)).json()
    return next(i["state"] for i in rows if i["id"] == iid)


def docs(conn, iid):  # noqa: F811
    return {r[0]: r[1:] for r in conn.execute(
        "SELECT doc_type, extracted, extraction_model, extraction_confidence FROM document "
        "WHERE invoice_id=%s AND content IS NOT NULL", (iid,)).fetchall()}


def reviews(client, iid):
    acts = client.get("/v1/actions", headers=login(client, "approver@lender-a.example"),
                      params={"status": "proposed"}).json()
    return [a for a in acts if a["kind"] == "review" and a["invoice_id"] == iid]


INV = "INV-003"


def test_clean_documents_verify_the_invoice_and_store_fields_model_and_confidence(client, conn, root):  # noqa: F811
    prepare(client, conn, root, INV, None)
    iid = upload(client, root, INV)
    model = fake_for(root, INV)
    run(client, conn, reader_for(root, model))
    assert state(client, iid) == "verified"
    d = docs(conn, iid)
    ex, mdl, conf = d["invoice"]
    assert ex["invoice_no"] and ex["sources"]["total"]["quote"] and ex["review"] == []
    assert mdl == LITE and float(conf) == 0.97
    assert {r[0] for r in conn.execute(
        "SELECT signal FROM evidence_item WHERE invoice_id=%s", (iid,))} >= {
        "irn_valid_matching", "po_matching", "grn_matching"}
    assert {c.model for c in model.calls} == {LITE}  # nothing needed Flash


def test_low_confidence_escalates_from_flash_lite_to_flash(client, conn, root):  # noqa: F811
    prepare(client, conn, root, INV, None)
    iid = upload(client, root, INV, ("invoice",))
    model = fake_for(root, INV, kinds=("invoice",))
    h = Document(pdf_of(root, INV, "invoice")).sha256
    good = model.truth[("extract", h)]
    model.truth[("classify", h)] = [{"doc_type": "invoice", "confidence": 0.6},
                                    {"doc_type": "invoice", "confidence": 0.97}]
    model.truth[("extract", h)] = [good | {"confidence": 0.5}, good]
    run(client, conn, reader_for(root, model))
    assert [(c.task, c.model) for c in model.calls] == [
        ("classify", LITE), ("classify", FLASH), ("extract", LITE), ("extract", FLASH)]
    assert docs(conn, iid)["invoice"][1] == FLASH
    assert docs(conn, iid)["invoice"][0]["review"] == []  # no PO or GRN yet: stays ingested
    assert state(client, iid) == "ingested"


def test_two_failures_end_in_human_review(client, conn, root):  # noqa: F811
    prepare(client, conn, root, INV, None)
    iid = upload(client, root, INV, ("invoice",))
    model = fake_for(root, INV, kinds=("invoice",))
    h = Document(pdf_of(root, INV, "invoice")).sha256
    model.truth[("extract", h)] = [model.truth[("extract", h)] | {"confidence": 0.4}] * 2
    run(client, conn, reader_for(root, model))
    assert state(client, iid) == "needs_review"
    assert len([c for c in model.calls if c.task == "extract"]) == 2  # Flash-Lite, Flash, then a person


def test_failed_quote_voids_the_field_and_sends_the_invoice_to_review(client, conn, root):  # noqa: F811
    prepare(client, conn, root, INV, None)
    iid = upload(client, root, INV, ("invoice",))
    t = truth_of(root, INV, "invoice")
    bad = deepcopy(t["sources"]) | {"total": {"page": 1, "quote": "Total: 9,99,99,999.00"}}
    run(client, conn, reader_for(root, fake_for(root, INV, {"invoice": {"sources": bad}}, ("invoice",))))
    ex = docs(conn, iid)["invoice"][0]
    assert "total" not in ex and "total: no quote found in the document" in ex["review"]
    assert state(client, iid) == "needs_review"
    assert reviews(client, iid)


def test_arithmetic_checksum_and_threshold_failures_are_not_used(client, conn, root):  # noqa: F811
    t = truth_of(root, INV, "invoice") | {"confidence": 0.97}
    text = pdf_text(pdf_of(root, INV, "invoice"))
    ok, problems = check_fields("invoice", t, text)
    assert problems == [] and ok["total"] == t["total"]
    bad = t | {"buyer_gstin": "29AABCZ9999B1ZZ", "confidences": {"total": 0.5}}
    clean, problems = check_fields("invoice", bad, text)
    assert "buyer_gstin" not in clean and "total" not in clean and len(problems) >= 2


def test_disagreement_with_the_gstr1_record_is_stored_as_mismatch_evidence(client, conn, root):  # noqa: F811
    g = json.loads((root[0] / "gst/gstr1.json").read_text())
    no = next(i["invoice_no"] for i in root[1]["invoices"] if i["id"] == INV)
    for r in g:
        for b in r["b2b"]:
            for i in b["inv"]:
                if i["inum"] == no:
                    i["val"] += 1000
    (root[0] / "gst/gstr1_bad.json").write_text(json.dumps(g))
    prepare(client, conn, root, INV, "gstr1_bad")
    iid = upload(client, root, INV, ("invoice",))
    run(client, conn, reader_for(root, fake_for(root, INV, kinds=("invoice",))))
    (m,) = docs(conn, iid)["invoice"][0]["mismatches"]
    assert m["field"] == "total" and m["between"] == ["invoice", "gstr1"]
    assert state(client, iid) == "needs_review"


def test_three_way_mismatch_is_found_in_code_then_explained_and_a_person_resolves_it(client, conn, root):  # noqa: F811
    prepare(client, conn, root, INV, None)
    iid = upload(client, root, INV)
    po = truth_of(root, INV, "po")
    items = deepcopy(po["line_items"])
    items[0]["qty"] += 5
    model = fake_for(root, INV, {"po": {"line_items": items}})
    run(client, conn, reader_for(root, model))
    (m,) = docs(conn, iid)["po"][0]["mismatches"]
    assert m["between"] == ["po", "invoice"] and m["values"]["po"] == m["values"]["invoice"] + 5
    assert len([c for c in model.calls if c.task == "mismatch_note"]) == 1  # code first, then words
    assert state(client, iid) == "needs_review"
    (a,) = reviews(client, iid)
    assert a["draft"]["mismatches"][0]["note"].startswith("The quantity")
    r = client.post(f"/v1/invoices/{iid}/resolve-review", headers=login(client))
    assert r.status_code == 200 and state(client, iid) == "verified"
    assert client.post(f"/v1/invoices/{iid}/resolve-review", headers=login(client)).status_code == 409


def test_three_way_pure():
    inv = {"po_ref": "P1", "invoice_no": "N1", "buyer_gstin": "G", "line_items": [{"hsn": "1", "qty": 5}]}
    po = {"invoice_ref": "P1", "buyer_gstin": "G", "line_items": [{"hsn": "1", "qty": 5}]}
    grn = {"invoice_ref": "N1", "buyer_gstin": "G", "line_items": [{"hsn": "1", "qty": 4}]}
    assert three_way({"invoice": inv, "po": po}) == []
    (m,) = three_way({"invoice": inv, "po": po, "grn": grn})
    assert m["between"] == ["grn", "invoice"] and m["values"] == {"grn": 4, "invoice": 5}


def test_text_in_a_document_is_data_an_injection_changes_nothing(client, conn, root):  # noqa: F811
    inv = root[1]["injection_samples"][0].split("/")[1]  # a PO carrying the planted instruction
    prepare(client, conn, root, inv, None)
    iid = upload(client, root, inv, ("po",))
    assert b"ignore all previous instructions" in pdf_of(root, inv, "po")
    rogue = {"po": {"action": "approve_advance", "state": "verified", "doc_type": "invoice"}}
    model = fake_for(root, inv, rogue, ("po",))
    before = state(client, iid)
    run(client, conn, reader_for(root, model))
    assert state(client, iid) == before == "ingested"
    ex = docs(conn, iid)["po"][0]
    assert "action" not in ex and "state" not in ex  # only the schema's fields are kept
    assert conn.execute("SELECT count(*) FROM advance WHERE invoice_id=%s", (iid,)).fetchone()[0] == 0
    assert conn.execute("SELECT count(*) FROM action_request WHERE invoice_id=%s AND kind <> 'doc_link'",
                        (iid,)).fetchone()[0] == 0


def test_a_document_outside_the_synthetic_manifest_is_refused_and_goes_to_review(client, conn, root):  # noqa: F811
    prepare(client, conn, root, INV, None)
    iid = upload(client, root, INV, ("invoice",))
    model = fake_for(root, INV, kinds=("invoice",))
    client_ = ModelClient(model, manifest_hashes=frozenset())
    run(client, conn, Reader(client_))
    assert model.calls == [] and state(client, iid) == "needs_review"
    assert "synthetic manifest" in docs(conn, iid)["invoice"][0]["review"][0]


def test_a_second_run_over_the_same_documents_makes_zero_calls(root):  # noqa: F811
    cache, doc = MemoryCache(), Document(pdf_of(root, INV, "invoice"))
    first = reader_for(root, fake_for(root, INV, kinds=("invoice",)), cache)
    a = first.read(doc)
    silent = FakeModel({})  # would raise KeyError on any call
    second = reader_for(root, silent, cache)
    assert second.read(doc) == a and silent.calls == [] and second.client.stats["misses"] == 0


def test_without_a_reader_the_runner_ignores_uploads(client, conn, root):  # noqa: F811
    iid = upload(client, root, INV, ("invoice",))
    drain(conn.info.dsn, SECRET, client)
    assert state(client, iid) == "ingested" and docs(conn, iid)["invoice"][0] is None
