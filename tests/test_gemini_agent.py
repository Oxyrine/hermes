"""Ticket 22: the Gemini function-calling loop, driven by a stubbed model against the real API."""

import psycopg
import pytest
from fastapi.testclient import TestClient

from hermes.agent import GeminiAgent, ModelLimit, ScriptedAgent, make_agent
from hermes.api import create_app
from test_seeded_invoice_api import SECRET, login, seeded_invoice_id

TRADER = {"udyam_urn": "UDYAM-XX-00-0000001", "classification": "micro", "enterprise_type": "trading",
          "registration_date": "2020-01-01", "contract_date": "2021-01-01", "supply_date": "2021-02-01"}


@pytest.fixture
def client(dsn):
    return TestClient(create_app(dsn, secret=SECRET, env="development"))


def setup(client, dsn, script, **kw):
    """An agent whose model replays `script` (a list of replies; an Exception is raised)."""
    h = login(client, "agent@lender-a.example")
    inv = seeded_invoice_id(client, h)
    replies = iter(script)

    def model(system, msgs, decls):
        r = next(replies)
        if isinstance(r, Exception):
            raise r
        return {"calls": [{"name": n, "args": a} for n, a in r], "tokens_in": 10, "tokens_out": 5}

    agent = GeminiAgent(client, h["Authorization"].split()[1], model, "stub", **kw)
    return agent, inv, {"kind": "deadline.passed", "invoice_id": inv, "payload": {"as_of": "2026-11-14"}}


def actions(dsn, kind="review"):
    with psycopg.connect(dsn) as c:
        return [r[0] for r in c.execute("SELECT draft FROM action_request WHERE kind=%s", (kind,))]


def test_cap_reached_stops_and_proposes_a_review(client, dsn):
    agent, _, ev = setup(client, dsn, [[("read_invoice", {})]] * 20, max_calls=3)
    agent.handle(ev)
    assert agent.tool_calls == 3  # 2 reads, then the review proposal: never past the cap
    (draft,) = actions(dsn)
    assert "cap of 3" in draft["reason"] and draft["cites"] == {"engine_runs": [], "document_ids": []}
    assert (agent.tokens_in, agent.tokens_out) == (30, 15)


def test_a_tool_off_the_allowlist_is_refused_and_recorded(client, dsn):
    agent, _, ev = setup(client, dsn, [[("sql_query", {"q": "select 1"})],
                                          [("propose_action", {"kind": "review", "draft": {"reason": "x"}})]])
    agent.handle(ev)
    assert agent.refused == ["sql_query"]
    (draft,) = actions(dsn)
    assert draft["reason"] == "x" and "sql_query" not in str(agent.runs)


def test_manual_review_stops_the_loop_and_the_review_cites_the_engine_run(client, dsn):
    agent, _, ev = setup(client, dsn, [[("run_eligibility", {"inputs": TRADER})],
                                          [("read_invoice", {})]])  # never reached
    agent.handle(ev)
    assert agent.tool_calls == 2
    (draft,) = actions(dsn)
    (run,) = draft["cites"]["engine_runs"]
    assert run["engine"] == "eligibility" and run["input_hash"] and "manual review" in draft["reason"]


def test_daily_model_limit_routes_the_invoice_to_review(client, dsn):
    agent, _, ev = setup(client, dsn, [ModelLimit("429")])
    agent.handle(ev)
    assert "daily model limit" in actions(dsn)[0]["reason"]


def test_scripted_is_the_default_runner(client, monkeypatch):
    monkeypatch.delenv("HERMES_AGENT_RUNNER", raising=False)
    assert isinstance(make_agent(client, "t"), ScriptedAgent)


def test_a_failing_event_is_retried_then_set_aside_without_blocking_the_rest(dsn):
    from hermes.dispatcher import drain

    class Boom:
        def request(self, *a, **k):
            raise RuntimeError("down")

    with psycopg.connect(dsn, autocommit=True) as c:
        t, inv = c.execute("SELECT tenant_id, id FROM invoice").fetchone()
        for _ in range(2):
            c.execute("INSERT INTO event_queue (tenant_id, invoice_id, kind, payload) VALUES "
                      "(%s,%s,'bank_rate.changed','{\"as_of\":\"2026-11-14\"}')", (t, inv))
        for _ in range(5):
            assert drain(dsn, SECRET, Boom()) == 0
            c.execute("UPDATE event_queue SET available_at=now()")
        assert c.execute("SELECT attempts, dead_at IS NOT NULL FROM event_queue").fetchall() == [(5, True)] * 2
        assert drain(dsn, SECRET, Boom()) == 0
        assert c.execute("SELECT count(*) FROM agent_run WHERE status='failed'").fetchone()[0] == 10
