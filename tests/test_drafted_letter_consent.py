"""Ticket 24: model-drafted letter with checks, supplier discount, below-floor lender consent.
Through the API with the fake model; no API key."""

import psycopg
import pytest
from fastapi.testclient import TestClient

from hermes.api import create_app
from hermes.dispatcher import drain
from hermes.ledger import service
from hermes.llm import FakeModel, ModelClient, RateLimited
from test_advance_clock_overdue import late_buyer, state
from test_offer_approval_close import pending
from test_seeded_invoice_api import SECRET, login, seeded_invoice_id

CLEAN = "Dear {{buyer_name}},\n\nWe write about invoice {{invoice_no}}. {{supplier_name}} offers INR {{offer}} to settle."


@pytest.fixture
def db(dsn):
    with psycopg.connect(dsn, autocommit=True) as c:
        yield c


def app_with(dsn, body):
    """An app whose fake model answers every letter request with `body` (or raises it)."""
    class Any(FakeModel):
        def generate(self, req):
            self.calls.append(req)
            if isinstance(body, Exception):
                raise body
            return {"body": body}

    return TestClient(create_app(dsn, secret=SECRET, env="development",
                                 model=ModelClient(Any({}), data_mode="real")))


def offer(client, dsn):
    h = login(client)
    inv = seeded_invoice_id(client, h)
    late_buyer(client, h, inv)
    drain(dsn, SECRET, client)
    sup = login(client, "supplier@sundaram.example")
    (a,) = pending(client, sup)
    return h, inv, sup, a


def test_clean_draft_is_accepted_and_numbers_come_from_the_engine(dsn):
    a = offer(app_with(dsn, CLEAN), dsn)[3]
    d = a["draft"]
    assert d["letter_source"] == "model" and "{{" not in d["letter"]
    assert f"INR {d['offer']}" in d["letter"] and "Dear Meridian Heavy Engineering" in d["letter"]
    assert "defers the buyer's tax deduction" in d["letter"]  # neutral notes, nothing stronger


@pytest.mark.parametrize("body", [
    CLEAN + " It is 45 days late.",  # stray digit
    CLEAN + " Otherwise we may take legal action.",  # banned phrase
    "Dear {{buyer_name}}, please pay.",  # no offer placeholder
    CLEAN + " {{nonsense}}"])
def test_bad_draft_falls_back_to_the_plain_template(dsn, body):
    d = offer(app_with(dsn, body), dsn)[3]["draft"]
    assert d["letter_source"] == "template" and "This letter is a draft for" in d["letter"]
    assert "defers the buyer's tax deduction" in d["letter"]


@pytest.mark.parametrize("model", [None, RateLimited(daily=True)])
def test_no_model_and_exhausted_limit_still_complete_the_flow(dsn, db, model):
    client = (TestClient(create_app(dsn, secret=SECRET, env="development")) if model is None
              else app_with(dsn, model))
    _h, inv, sup, a = offer(client, dsn)
    assert a["draft"]["letter_source"] == "template"
    assert client.post(f"/v1/actions/{a['id']}/approve", headers=sup).status_code == 200
    assert state(db, inv) == "settlement_offered"


def test_discount_is_recomputed_by_the_engine(dsn):
    client = app_with(dsn, CLEAN)
    _h, _inv, sup, a = offer(client, dsn)
    r = client.post(f"/v1/actions/{a['id']}/discount", headers=sup, json={"discount_percent": "50"})
    assert r.status_code == 200, r.text
    d = r.json()["draft"]
    assert d["discount_percent"] == "50.00" or d["discount_percent"].startswith("50")
    assert float(d["offer"].replace(",", "")) < float(a["draft"]["offer"].replace(",", ""))
    assert f"INR {d['offer']}" in d["letter"]
    assert client.post(f"/v1/actions/{a['id']}/discount", headers=sup,
                       json={"discount_percent": "abc"}).status_code == 422
    assert client.post(f"/v1/actions/{a['id']}/discount", headers=sup,
                       json={"discount_percent": "101"}).status_code == 422
    assert client.post(f"/v1/actions/{a['id']}/discount", headers=login(client),
                       json={"discount_percent": "5"}).status_code == 403


def test_below_floor_is_held_for_lender_consent_then_released(dsn, monkeypatch):
    real = service.ENGINES["settlement"]
    monkeypatch.setitem(service.ENGINES, "settlement",
                        lambda i: real({**i, "agreed_costs": "400000"}))  # floor above the offer
    client = app_with(dsn, CLEAN)
    _h, inv, sup, a = offer(client, dsn)
    assert a["draft"]["needs_lender_consent"] is True
    lender = login(client, "approver@lender-a.example")
    (queued,) = pending(client, lender)  # in the lender's queue
    assert queued["id"] == a["id"]
    assert client.post(f"/v1/actions/{a['id']}/approve", headers=sup).json()["status"] == "proposed"
    with psycopg.connect(dsn, autocommit=True) as c:
        assert state(c, inv) == "overdue"  # held: supplier alone cannot send it
        r = client.post(f"/v1/actions/{a['id']}/approve", headers=lender)
        assert r.status_code == 200 and r.json()["status"] == "approved"
        assert state(c, inv) == "settlement_offered"
        who, at = c.execute("SELECT u.email, a.lender_consent_at FROM action_request a "
                            "JOIN app_user u ON u.id=a.lender_consent_by").fetchone()
        assert who == "approver@lender-a.example" and at is not None


def test_at_or_above_floor_needs_only_the_supplier(dsn):
    client = app_with(dsn, CLEAN)
    _h, _inv, sup, a = offer(client, dsn)
    assert a["draft"]["needs_lender_consent"] is False
    assert client.post(f"/v1/actions/{a['id']}/approve", headers=sup).json()["status"] == "approved"
