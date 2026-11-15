"""Ticket 27 through the HTTP API: every figure opens its source, and an engine run recomputes."""

import json

import psycopg
import pytest
from fastapi.testclient import TestClient

from hermes.api import create_app

AS_OF = "2026-11-14"
SECRET = "test-secret-not-for-production-0123456789"


@pytest.fixture
def client(dsn):
    return TestClient(create_app(dsn, secret=SECRET, env="development"))


def login(client, email="ops@lender-a.example"):
    r = client.post("/dev/login", json={"email": email})
    return {"Authorization": f"Bearer {r.json()['token']}"}


def view(client, h):
    (row,) = client.get("/v1/invoices", headers=h).json()
    return client.get(f"/v1/invoices/{row['id']}", params={"as_of": AS_OF}, headers=h).json()


def test_every_figure_carries_a_source_that_resolves(client):
    h = login(client)
    v = view(client, h)
    figures = ["total", "invoice_no", "delivery_date", "written_days", "eligibility", "acceptance", "due",
               "interest_from", "score", "band", "principal", "interest", "claim_value", "exposure", "ltv"]
    assert set(figures) <= set(v["sources"])
    for name in figures:
        ref = v["sources"][name]
        r = client.get(f"/v1/sources/{ref['kind']}/{ref['id']}", headers=h)
        assert r.status_code == 200, (name, r.text)
        if ref["kind"] == "engine_run":
            assert r.json()["engine"] and r.json()["rule_version"] and r.json()["inputs"]
            assert r.json()["reasons"] is not None
    # an extracted value opens its document with page and quote
    d = v["sources"]["delivery_date"]
    assert (d["kind"], d["page"], d["quote"]) == ("document", 1, "Goods received on 01-08-2026")
    doc = client.get(f"/v1/sources/document/{d['id']}", headers=h).json()
    assert doc["has_content"] is False and doc["content_url"] is None and doc["doc_type"] == "grn"
    # each evidence contribution opens its source record
    kinds = {x["signal"]: x["ref"]["kind"] for x in v["evidence"]["contributions"]}
    assert kinds["ims_accepted"] == "ims_event" and kinds["grn_matching"] == "document"
    assert kinds["irn_valid_matching"] == "evidence_item"
    for x in v["evidence"]["contributions"]:
        assert client.get(f"/v1/sources/{x['ref']['kind']}/{x['ref']['id']}", headers=h).status_code == 200


def test_provisional_marking_and_recompute(client, dsn):
    h = login(client)
    v = view(client, h)
    ref = v["sources"]["due"]
    assert ref["engine"] == "deadline" and ref["provisional"] is True  # day-count awaits legal review
    r = client.post(f"/v1/engine-runs/{ref['id']}/recompute", headers=h)
    assert r.status_code == 200 and r.json()["matches"] is True and r.json()["differs_in"] == []
    # tamper with the stored inputs: the recomputed output no longer matches
    with psycopg.connect(dsn, autocommit=True) as c:
        c.execute("UPDATE engine_run SET inputs=%s::jsonb WHERE id=%s",
                  (json.dumps({"delivery": "2026-08-05", "written_days": 45}), ref["id"]))
    bad = client.post(f"/v1/engine-runs/{ref['id']}/recompute", headers=h).json()
    assert bad["matches"] is False and "result" in bad["differs_in"]


def test_sources_are_scoped(client):
    h, sup = login(client), login(client, "supplier@sundaram.example")
    v = view(client, h)
    assert client.get(f"/v1/sources/engine_run/{v['sources']['due']['id']}", headers=sup).status_code == 200
    assert client.get("/v1/sources/engine_run/not-a-uuid", headers=h).status_code == 404
    assert client.get("/v1/sources/nope/1", headers=h).status_code == 404
    assert client.post("/v1/engine-runs/00000000-0000-0000-0000-000000000000/recompute",
                       headers=h).status_code == 404


def test_portfolio_and_queue_carry_sources(client):
    h = login(client)
    (row,) = client.get("/v1/portfolio", params={"as_of": AS_OF}, headers=h).json()
    for k in ("band", "due", "claim_value", "exposure", "ltv"):
        assert row["sources"][k]["kind"] == "engine_run"
    iid = view(client, h)["id"]
    agent = login(client, "agent@lender-a.example")
    r = client.post(f"/v1/invoices/{iid}/actions", json={"kind": "settlement_offer", "as_of": AS_OF},
                    headers=agent)
    assert r.status_code == 200, r.text
    (a,) = client.get("/v1/actions", headers=login(client, "supplier@sundaram.example")).json()
    assert {s["engine"] for s in a["sources"]} >= {"settlement", "deadline", "interest"}
    assert all(client.get(f"/v1/sources/engine_run/{s['id']}", headers=h).status_code == 200
               for s in a["sources"])
