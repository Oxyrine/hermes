"""Ticket 20: model-read objections and contract terms, confirmed by people. Fake model only."""

import json
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from hermes.api import create_app
from hermes.dispatcher import drain
from hermes.extraction import Reader
from hermes.llm import FakeModel, ModelClient, synthetic_hashes
from test_adapters import conn, invoice_id, pull, root, world  # noqa: F401
from test_seeded_invoice_api import SECRET, login

HERMES = "hermesops@hermes.example"


@pytest.fixture
def client(world):  # noqa: F811
    return TestClient(create_app(world, secret=SECRET, env="development"))


def emails(root):  # noqa: F811
    return [json.loads((root[0] / f["path"]).read_text()) for f in root[1]["files"] if f["kind"] == "email"]


def run_reader(client, conn, root, truth_for):  # noqa: F811
    """Drain the queue with a fake model whose answers come from truth_for(doc_type, content)."""
    truth, hashes = {}, set(synthetic_hashes(root[1]))
    for did, kind, content, sha in conn.execute(
            "SELECT id, doc_type, content, sha256 FROM document WHERE doc_type IN ('email','contract')"):
        hashes.add(sha)
        t = truth_for(kind, bytes(content), str(did))
        if t is not None:
            truth[("detect.objection" if kind == "email" else "extract.contract_terms", sha)] = t
    model = FakeModel(truth)
    reader = Reader(ModelClient(model, manifest_hashes=hashes))
    drain(conn.info.dsn, SECRET, client, reader)
    return model


def objection_truth(kind, content, _id):
    if kind != "email":
        return None
    e = json.loads(content)
    m = e["messages"][0]
    ref = m["subject"].split()[-1]
    body = m["body"]
    hit = "We reject the goods" in body
    quote = next((ln for ln in body.splitlines() if ln.startswith("We reject")), None)
    return {"is_objection": hit, "confidence": 0.95 if hit else 0.3, "invoice_refs": [ref],
            **({"raised_on": m["sent_at"][:10], "quote": quote} if hit else {})}


def load_threads(client, conn, root):  # noqa: F811
    for sid in ("S1", "S2", "S3"):
        pull(client, conn, root, sid, "documents")
        pull(client, conn, root, sid, "email")


def objection_actions(client):
    return [a for a in client.get("/v1/actions", headers=login(client, HERMES),
                                  params={"status": "proposed"}).json() if a["kind"] == "objection"]


@pytest.fixture
def ops(conn):  # noqa: F811
    conn.execute("INSERT INTO app_user (tenant_id, email, role) SELECT tenant_id, "
                 "'hermesops@hermes.example', 'hermes_ops' FROM app_user LIMIT 1")


def test_every_labelled_objection_is_surfaced_and_nothing_else(client, conn, root, ops):  # noqa: F811
    load_threads(client, conn, root)
    before = conn.execute("SELECT count(*) FROM engine_run").fetchone()[0]
    model = run_reader(client, conn, root, objection_truth)
    assert conn.execute("SELECT count(*) FROM engine_run").fetchone()[0] == before  # nothing re-ran
    labels = [e["label"] for e in emails(root)]
    wanted = {l["quote"] for l in labels if l["is_objection"]}
    got = {a["draft"]["quote"] for a in objection_actions(client)}
    assert len(wanted) == 9 and got == wanted  # recall 100%, no false positives on delays/requests/noise
    assert {c.model for c in model.calls} == {"gemini-3.8-flash"}  # Flash only
    assert all(c.temperature == 0.0 for c in model.calls)
    assert conn.execute("SELECT count(*) FROM evidence_item WHERE signal='written_objection_15d'"
                        ).fetchone()[0] == 0


def test_scenario_4_buyer_disputes_on_day_9_person_confirms_dates_and_collateral_move(
        client, conn, root, ops):  # noqa: F811
    load_threads(client, conn, root)
    lab = next(e["label"] for e in emails(root) if e["label"]["days_after_delivery"] == 9)
    inv = invoice_id(client, root, lab["invoice_id"])
    h = login(client)
    v0 = client.get(f"/v1/invoices/{inv}", headers=h).json()
    run_reader(client, conn, root, objection_truth)
    assert client.get(f"/v1/invoices/{inv}", headers=h).json()["deadline"] == v0["deadline"]  # not yet
    act = next(a for a in objection_actions(client) if a["invoice_id"] == inv)
    assert act["draft"]["quote"] == lab["quote"] and act["draft"]["raised_on"] == lab["raised_on"]
    assert act["needs"] == ["hermes_ops", "supplier"]
    hops = login(client, HERMES)
    sup = login(client, next(f"supplier@{s['name'].split()[0].lower()}.example"
                             for s in root[1]["suppliers"]
                             if s["id"] == next(i["supplier"] for i in root[1]["invoices"]
                                                if i["id"] == lab["invoice_id"])))
    # the approver corrects the date: the buyer withdrew the objection on day 20
    removed = (date.fromisoformat(v0["deadline"]["acceptance"]) + timedelta(days=20)).isoformat()
    r = client.post(f"/v1/actions/{act['id']}/edit", headers=hops, json={"changes": {"removed_on": removed}})
    assert r.status_code == 200 and r.json()["edit_difference"]["removed_on"]["to"] == removed
    assert client.post(f"/v1/actions/{act['id']}/edit", headers=hops,
                       json={"changes": {"raised_on": "not a date"}}).status_code == 422
    assert client.post(f"/v1/actions/{act['id']}/edit", headers=hops,
                       json={"changes": {"quote": "forged"}}).status_code == 422
    assert client.post(f"/v1/actions/{act['id']}/approve", headers=hops).json()["status"] == "proposed"
    assert client.get(f"/v1/invoices/{inv}", headers=h).json()["deadline"] == v0["deadline"]
    assert client.post(f"/v1/actions/{act['id']}/approve", headers=sup).json()["status"] == "approved"
    drain(conn.info.dsn, SECRET, client)  # action.approved: the agent re-reads, engines re-run
    v1 = client.get(f"/v1/invoices/{inv}", headers=h).json()
    assert v1["deadline"]["basis"] == "objection_removed" and v1["deadline"]["acceptance"] == removed
    assert v1["deadline"]["due"] != v0["deadline"]["due"]
    assert conn.execute("SELECT due_date::text FROM invoice WHERE id=%s", (inv,)).fetchone()[0] == \
        v1["deadline"]["due"]
    assert v1["evidence"]["score"] == max(0, v0["evidence"]["score"] - 20) and v1["needs_review"]
    assert {r[0] for r in conn.execute(  # collateral re-ran on the moved due date
        "SELECT inputs->>'due_date' FROM engine_run WHERE invoice_id=%s AND engine='collateral'",
        (inv,))} >= {v0["deadline"]["due"], v1["deadline"]["due"]}


def test_bad_readings_go_to_review_not_to_confirmation(client, conn, root, ops):  # noqa: F811
    load_threads(client, conn, root)
    run_reader(client, conn, root, lambda k, c, i: (
        objection_truth(k, c, i) | {"quote": "invented sentence"}) if k == "email" else None)
    assert objection_actions(client) == []
    reviews = [a for a in client.get("/v1/actions", headers=login(client, "approver@lender-a.example"),
                                     params={"status": "proposed"}).json() if a["kind"] == "review"]
    assert reviews and "the quote is not in the document" in reviews[0]["draft"]["problems"]


def contract_truth(kind, content, _id):
    if kind != "contract":
        return None
    text = content.decode("latin-1")
    days = next((int(w) for w in ("30", "60", "45") if f"within {w} days" in text), None)
    out = {"confidence": 0.95, "from_event": "acceptance", "page": 1}
    if days is None:
        return out
    return out | {"payment_days": days, "clause_quote": f"Clause 7 Payment: Payment shall be made within "
                  f"{days} days from the date of acceptance."}


def test_contract_term_is_stored_only_after_hermes_ops_confirms_and_then_drives_the_deadline(
        client, conn, root, ops):  # noqa: F811
    load_threads(client, conn, root)
    inv_id = next(i for i in root[1]["scenarios"]["contract_term"]
                  if json.loads((root[0] / f"docs/{i}/contract.truth.json").read_text())["payment_days"] == 30)
    inv = invoice_id(client, root, inv_id)
    h = login(client)
    assert conn.execute("SELECT c.written_payment_days FROM contract c JOIN invoice i ON i.contract_id=c.id "
                        "WHERE i.id=%s", (inv,)).fetchone()[0] is None  # nothing stored on ingest
    v0 = client.get(f"/v1/invoices/{inv}", headers=h).json()
    model = run_reader(client, conn, root, contract_truth)
    assert {c.model for c in model.calls if c.task.startswith("extract")} == {"gemini-3.8-flash"}
    queue = client.get("/v1/actions", headers=login(client, HERMES), params={"status": "proposed"}).json()
    act = next(a for a in queue if a["kind"] == "contract_terms" and a["invoice_id"] == inv)
    assert act["draft"]["payment_days"] == "30" and act["draft"]["page"] == 1
    assert client.get(f"/v1/invoices/{inv}", headers=h).json()["deadline"] == v0["deadline"]
    hops = login(client, HERMES)
    assert client.post(f"/v1/actions/{act['id']}/edit", headers=hops,
                       json={"changes": {"payment_days": "-5"}}).status_code == 422
    r = client.post(f"/v1/actions/{act['id']}/edit", headers=hops, json={"changes": {"payment_days": "20"}})
    assert r.json()["edit_difference"] == {"payment_days": {"from": "30", "to": "20"}}
    assert client.post(f"/v1/actions/{act['id']}/approve", headers=login(client, "ops@lender-a.example")
                       ).status_code == 403
    assert client.post(f"/v1/actions/{act['id']}/approve", headers=hops).json()["status"] == "approved"
    row = conn.execute("SELECT c.written_payment_days, c.terms_source->>'quote', c.terms_confirmed_by IS NOT NULL, "
                       "c.terms_confirmed_at IS NOT NULL FROM contract c JOIN invoice i ON i.contract_id=c.id "
                       "WHERE i.id=%s", (inv,)).fetchone()
    assert row[0] == 20 and row[1].startswith("Clause 7 Payment") and row[2:] == (True, True)
    v1 = client.get(f"/v1/invoices/{inv}", headers=h).json()
    assert v1["deadline"]["due"] == (date.fromisoformat(v1["deadline"]["acceptance"]) + timedelta(days=20)).isoformat()
