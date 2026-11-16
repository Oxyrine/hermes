"""Ticket 34: the demo makes no model calls, and every API response carries the security headers."""

import psycopg
from fastapi.testclient import TestClient

from hermes.api import create_app
from test_seeded_invoice_api import SECRET


def test_demo_makes_zero_model_calls(dsn, monkeypatch):
    from hermes.demo import play

    monkeypatch.delenv("GEMINI_API_KEY", raising=False)  # a model call could not be made anyway
    play(dsn, SECRET, TestClient(create_app(dsn, secret=SECRET, env="development")), lambda _: None)
    with psycopg.connect(dsn, autocommit=True) as c:
        assert c.execute("SELECT count(*) FROM model_cache").fetchone()[0] == 0
        assert c.execute("SELECT count(*) FROM agent_run WHERE runner<>'scripted' OR model IS NOT NULL "
                         "OR tokens_in IS NOT NULL").fetchone()[0] == 0
        assert c.execute("SELECT count(*) FROM agent_run").fetchone()[0] > 0


def test_responses_carry_security_headers(dsn):
    r = TestClient(create_app(dsn, secret=SECRET)).get("/v1/invoices")  # 401 is still a response
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["referrer-policy"] == "no-referrer"
