"""Ticket 33: webhooks to lenders. No network beyond a receiver on localhost."""
# ruff: noqa: F811

import hmac
import json
import threading
from datetime import date
from http.server import BaseHTTPRequestHandler, HTTPServer

import psycopg
import pytest
from fastapi.testclient import TestClient

from hermes import webhooks
from hermes.api import create_app
from hermes.dispatcher import drain
from hermes.ledger import service, states
from test_adapters import conn, funded_reversal, pull, root, world  # noqa: F401
from test_seeded_invoice_api import SECRET, login, seeded_invoice_id

KEY = "test-webhook-key"


@pytest.fixture(autouse=True)
def _key(monkeypatch):
    monkeypatch.setenv("HERMES_WEBHOOK_KEY", KEY)


@pytest.fixture
def client(dsn):
    return TestClient(create_app(dsn, secret=SECRET, env="development"))


@pytest.fixture
def adapters_client(world):
    return TestClient(create_app(world, secret=SECRET, env="development"))


@pytest.fixture
def db(dsn):
    with psycopg.connect(dsn, autocommit=True) as c:
        yield c


def subscribe(client, h, url="http://127.0.0.1:9/hook", **body):
    return client.post("/v1/webhooks", headers=h, json={"url": url} | body)


def tenant_of(db):
    return db.execute("SELECT id FROM tenant").fetchone()[0]


def rows(db, event=None):
    return db.execute("SELECT event, payload FROM webhook_delivery WHERE %s::text IS NULL OR "
                      "event=%s ORDER BY created_at, id", (event, event)).fetchall()


def test_subscribe_returns_the_secret_once_and_never_logs_it(client, db):
    h = login(client)
    r = subscribe(client, h, events=["invoice.hard_flag"])
    assert r.status_code == 200, r.text
    sub = r.json()
    assert sub["secret"] == webhooks.secret_for(KEY, sub["id"]) and sub["events"] == ["invoice.hard_flag"]
    listed = client.get("/v1/webhooks", headers=h).json()
    assert [s["id"] for s in listed] == [sub["id"]] and "secret" not in listed[0]
    assert sub["secret"] not in json.dumps(db.execute("SELECT after FROM audit_log").fetchall(), default=str)
    assert subscribe(client, h, events=["nope"]).status_code == 422
    assert subscribe(client, h, url=None).status_code == 422
    assert subscribe(client, login(client, "supplier@sundaram.example")).status_code == 403


@pytest.mark.parametrize("url", [
    "http://example.com/hook", "https://127.0.0.1/hook", "https://10.1.2.3/hook",
    "https://[::1]/hook", "https://169.254.169.254/latest", "https://localhost/hook", "ftp://x/y"])
def test_outside_development_only_public_https_is_accepted(url):
    with pytest.raises(ValueError):
        webhooks.check_url(url, dev=False)
    if url.startswith("http"):
        webhooks.check_url(url, dev=True)  # development allows local receivers
    webhooks.check_url("https://93.184.216.34/hook", dev=False)


def test_subscription_is_refused_in_production_for_a_loopback_endpoint(dsn):
    import time

    import jwt
    prod = TestClient(create_app(dsn, secret=SECRET, env="production"))
    with psycopg.connect(dsn, autocommit=True) as c:
        t = str(tenant_of(c))
    tok = jwt.encode({"sub": "u", "tenant": t, "role": "lender_ops", "exp": int(time.time()) + 60},
                     SECRET, algorithm="HS256")
    r = prod.post("/v1/webhooks", headers={"Authorization": f"Bearer {tok}"},
                  json={"url": "https://127.0.0.1/hook"})
    assert r.status_code == 422 and "private" in r.json()["detail"]


def test_only_subscribed_events_of_the_own_tenant_are_queued(client, db):
    h = login(client)
    mine = subscribe(client, h, events=["invoice.hard_flag"]).json()["id"]
    other = db.execute("INSERT INTO tenant (name, kind, max_ltv, lender_rate_nominal) "
                       "SELECT 'Other', kind, max_ltv, lender_rate_nominal FROM tenant RETURNING id"
                       ).fetchone()[0]
    db.execute("INSERT INTO webhook_subscription (tenant_id, url, events) VALUES (%s,'http://x/y',%s)",
               (other, list(webhooks.EVENTS)))
    t = tenant_of_first(db)
    webhooks.publish(db, t, "invoice.hard_flag", {"invoice_id": "i1"})
    webhooks.publish(db, t, "invoice.state_changed", {"invoice_id": "i1"})  # not subscribed
    assert db.execute("SELECT subscription_id::text, event FROM webhook_delivery").fetchall() == [
        (mine, "invoice.hard_flag")]


def tenant_of_first(db):
    return db.execute("SELECT id FROM tenant ORDER BY name LIMIT 1").fetchone()[0]


def test_state_change_and_awaiting_lender_are_published_with_ids_only(client, db, monkeypatch):
    h = login(client)
    subscribe(client, h, events=["invoice.state_changed", "action.awaiting_lender"])
    inv = seeded_invoice_id(client, h)
    t = tenant_of(db)
    db.execute("UPDATE invoice SET state='ingested' WHERE id=%s", (inv,))
    db.execute("INSERT INTO evidence_item (tenant_id, invoice_id, signal, source_ref, detected_at) "
               "VALUES (%s,%s,'irn_valid_matching','{}',now())", (t, inv))
    states.transition(db, t, inv, "verified", {"matched": True}, "test")
    assert rows(db) == [("invoice.state_changed", {"invoice_id": inv})]
    real = service.ENGINES["settlement"]

    def needs_consent(inputs):
        out = real(inputs)
        out["result"]["needs_lender_consent"] = True
        return out

    monkeypatch.setitem(service.ENGINES, "settlement", needs_consent)
    a = service.propose_settlement_offer(db, t, inv, date(2026, 11, 14), "agent")
    assert rows(db, "action.awaiting_lender") == [
        ("action.awaiting_lender", {"invoice_id": inv, "action_id": a["id"]})]


def test_ltv_breach_is_published_by_the_tick_once_per_day(client, db):
    h = login(client)
    subscribe(client, h, events=["collateral.ltv_breach"])
    inv = seeded_invoice_id(client, h)
    db.execute("INSERT INTO advance (tenant_id, invoice_id, principal, nominal_rate, disbursed_on, status) "
               "SELECT tenant_id, id, 990000, 18, '2026-09-01', 'open' FROM invoice")
    for _ in range(2):
        assert client.post("/dev/tick", json={"date": "2026-11-14"}).status_code == 200
    assert rows(db) == [("collateral.ltv_breach", {"invoice_id": inv, "as_of": "2026-11-14"})]


# ---- delivery ----

def queue_one(client, db, event="invoice.state_changed", ids=None):
    sub = subscribe(client, login(client), url="http://127.0.0.1:9/hook").json()
    webhooks.publish(db, tenant_of(db), event, ids or {"invoice_id": "i1"})
    return sub


def test_delivery_is_signed_with_hmac_sha256_over_the_body(client, db):
    sub = queue_one(client, db)
    seen = []
    assert webhooks.deliver_due(db, KEY, True, lambda u, b, h: seen.append((u, b, h)) or 204) == 1
    _url, body, headers = seen[0]
    assert headers["X-Hermes-Signature"] == "sha256=" + hmac.new(
        sub["secret"].encode(), body, "sha256").hexdigest()
    sent = json.loads(body)
    assert sent["event"] == "invoice.state_changed" and sent["invoice_id"] == "i1"
    assert db.execute("SELECT attempts, last_status, delivered_at IS NOT NULL, next_attempt_at "
                      "FROM webhook_delivery").fetchone() == (1, 204, True, None)
    assert webhooks.deliver_due(db, KEY, True, lambda *a: 1 / 0) == 0  # delivered: not sent again


def test_failures_back_off_exponentially_are_recorded_and_stop_after_24_hours(client, db):
    queue_one(client, db)
    fail = {"n": 0}

    def post(*a):
        fail["n"] += 1
        if fail["n"] == 2:
            raise OSError("connection refused")
        return 500

    def make_due():
        db.execute("UPDATE webhook_delivery SET next_attempt_at=now() WHERE next_attempt_at IS NOT NULL")

    gaps = []
    for _ in range(3):
        assert webhooks.deliver_due(db, KEY, True, post) == 0
        gaps.append(db.execute("SELECT extract(epoch FROM next_attempt_at - now()) FROM webhook_delivery"
                               ).fetchone()[0])
        make_due()
    assert [round(g / 30) for g in gaps] == [1, 2, 4]  # 30s, 60s, 120s
    assert db.execute("SELECT status, error IS NOT NULL FROM webhook_attempt ORDER BY id").fetchall()[:3] == [
        (500, False), (None, True), (500, False)]
    # a delivery whose next retry would pass 24 hours is given up
    db.execute("UPDATE webhook_delivery SET created_at=now() - interval '23 hours 59 minutes', "
               "next_attempt_at=now()")
    webhooks.deliver_due(db, KEY, True, post)
    assert db.execute("SELECT next_attempt_at, delivered_at FROM webhook_delivery").fetchone() == (None, None)
    n = db.execute("SELECT count(*) FROM webhook_attempt").fetchone()[0]
    assert webhooks.deliver_due(db, KEY, True, post) == 0
    assert db.execute("SELECT count(*) FROM webhook_attempt").fetchone()[0] == n


def test_a_private_endpoint_is_refused_at_delivery_outside_development(client, db):
    queue_one(client, db)
    assert webhooks.deliver_due(db, KEY, False, lambda *a: 1 / 0) == 0
    assert "https" in db.execute("SELECT error FROM webhook_attempt").fetchone()[0]


# ---- scenario 6, in full ----

@pytest.fixture
def receiver():
    got = []

    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            got.append((self.headers, self.rfile.read(int(self.headers["Content-Length"]))))
            self.send_response(200)
            self.end_headers()

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}/hook", got
    srv.shutdown()


def test_scenario_6_ims_reversal_on_a_funded_invoice_reaches_a_local_receiver_signed(
        adapters_client, conn, root, receiver):
    url, got = receiver
    h = login(adapters_client)
    sub = subscribe(adapters_client, h, url=url, events=["invoice.hard_flag"]).json()
    inv, h = funded_reversal(adapters_client, conn, root)
    pull(adapters_client, conn, root, "S1", "ims_supplier_view", fixture="ims_supplier_view_reversal")
    drain(conn.info.dsn, SECRET, adapters_client)
    assert webhooks.deliver_due(conn, KEY, True) == 1
    (headers, body), = got
    assert headers["X-Hermes-Signature"] == webhooks.sign(sub["secret"], body)
    sent = json.loads(body)
    assert sent["event"] == "invoice.hard_flag" and sent["invoice_id"] == inv
    assert set(sent) == {"id", "event", "created_at", "invoice_id", "flag_id"}  # ids only
    assert conn.execute("SELECT delivered_at IS NOT NULL, (delivered_at - raised_at) < interval "
                        "'5 minutes' FROM hard_flag_event WHERE invoice_id=%s", (inv,)).fetchone() == (True, True)
