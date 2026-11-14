"""Ticket 32: the buyer's signed, read-only statement link."""

import psycopg
import pytest
from fastapi.testclient import TestClient

from hermes.api import create_app
from test_offer_approval_close import overdue, pending  # noqa: F401  (fixture)
from test_seeded_invoice_api import SECRET, login


@pytest.fixture
def db(dsn):
    with psycopg.connect(dsn, autocommit=True) as c:
        yield c


@pytest.fixture
def client(dsn):
    return TestClient(create_app(dsn, secret=SECRET, env="development"))


@pytest.fixture
def link(client, overdue):  # noqa: F811
    h, inv = overdue
    approver = login(client, "supplier@sundaram.example")
    (a,) = pending(client, approver)
    r = client.post(f"/v1/actions/{a['id']}/approve", headers=approver)
    return h, inv, r.json()["buyer_link"]


def test_valid_link_shows_the_statement_from_engine_output(client, link):
    h, inv, path = link
    r = client.get(path)
    assert r.status_code == 200, r.text
    s = r.json()
    view = client.get(f"/v1/invoices/{inv}", headers=h).json()
    assert s["invoice"]["invoice_no"] == view["invoice_no"] and s["invoice"]["total"] == view["total"]
    assert s["acceptance_date"] == view["deadline"]["acceptance"]
    assert s["due_date"] == view["deadline"]["due"]
    assert s["days_late"] > 0
    assert s["interest_to_date"] == view["claim"]["interest"]
    assert s["delivery_evidence"]
    assert len(s["notes"]) == 2
    assert "noindex" in r.headers["x-robots-tag"]


def test_tampered_and_expired_links_get_a_plain_refusal_and_no_data(client, link, dsn):
    _h, inv, path = link
    token = path.rsplit("/", 1)[1]
    from hermes import statement
    row = psycopg.connect(dsn).execute("SELECT tenant_id::text FROM invoice").fetchone()
    expired = statement.make_token(SECRET, row[0], inv, now=0)
    other_secret = statement.make_token("another-secret-0123456789-abcdefgh", row[0], inv)
    for bad in (token[:-2] + ("AA" if token[-2:] != "AA" else "BB"), expired, other_secret, "junk"):
        r = client.get(f"/public/statement/{bad}")
        assert r.status_code == 404 and r.json() == {"detail": "This link is not valid."}
        assert "noindex" in r.headers["x-robots-tag"]
        assert client.post(f"/public/statement/{bad}/respond", json={"choice": "will_pay"}).status_code == 404
    assert client.get(f"/public/statement/{login(client)['Authorization'].split()[1]}").status_code == 404


def test_link_exposes_one_invoice_only(client, link):
    _h, _inv, path = link
    body = client.get(path).text
    assert body.count("invoice_no") == 1
    assert client.get("/v1/invoices", params={}).status_code == 401  # the token opens nothing else


def test_opening_and_replying_add_audit_rows_and_an_event_without_waking_the_agent(client, link, db):
    _h, inv, path = link
    client.get(path)
    assert db.execute("SELECT count(*) FROM audit_log WHERE action='statement_opened' AND object_id=%s",
                      (inv,)).fetchone()[0] == 1
    assert client.post(path + "/respond", json={"choice": "nope"}).status_code == 422
    r = client.post(path + "/respond", json={"choice": "will_pay", "note": "paying Friday"})
    assert r.status_code == 200
    assert db.execute("SELECT payload->>'choice', done_at IS NOT NULL FROM event_queue WHERE "
                      "kind='buyer.responded'").fetchall() == [("will_pay", True)]
    assert db.execute("SELECT count(*) FROM audit_log WHERE action='buyer_response'").fetchone()[0] == 1
    assert db.execute("SELECT count(*) FROM payment").fetchone()[0] == 0  # Hermes takes no payment


def test_page_text_passes_the_banned_phrase_check(client, link):
    from hermes.statement import BANNED, NOTES
    _h, _inv, path = link
    text = " ".join(client.get(path).json()["notes"]) + " ".join(NOTES)
    assert not BANNED.search(text)
    assert BANNED.search("we will take legal action")  # the check does bite
