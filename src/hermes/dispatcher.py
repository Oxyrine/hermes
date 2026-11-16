"""Event dispatcher: claims one event at a time, takes a per-invoice lock, runs the agent,
releases. The lock is a Postgres advisory lock on the invoice id (session-level, so the agent's
own API calls, on other connections, are not blocked). `python -m hermes.dispatcher` drains the
queue against a running API (HERMES_API_URL)."""

import logging
import os
import time

import jwt
import psycopg
from psycopg.rows import dict_row

from hermes import webhooks
from hermes.agent import make_agent

CLAIM = (
    "UPDATE event_queue SET claimed_at=now() WHERE id=(SELECT id FROM event_queue WHERE "
    "done_at IS NULL AND dead_at IS NULL AND claimed_at IS NULL AND available_at<=now() AND id <> ALL(%s) "
    "ORDER BY id FOR UPDATE SKIP LOCKED LIMIT 1) "
    "RETURNING id, tenant_id::text, invoice_id::text, kind, payload")
log = logging.getLogger("hermes.dispatcher")
MAX_ATTEMPTS = 5
RETRY_AFTER = "1 minute"
LOCK = "SELECT pg_try_advisory_lock(hashtext(%s))"
UNLOCK = "SELECT pg_advisory_unlock(hashtext(%s))"


def drain(dsn: str, secret: str, http, reader=None, model=None) -> int:
    """Process every claimable event; returns how many ran. Events whose invoice is locked by
    another run stay in the queue."""
    done, skipped = 0, [0]
    with psycopg.connect(dsn, autocommit=True) as c:
        while ev := c.cursor(row_factory=dict_row).execute(CLAIM, (skipped,)).fetchone():
            if not c.execute(LOCK, (ev["invoice_id"],)).fetchone()[0]:
                c.execute("UPDATE event_queue SET claimed_at=NULL WHERE id=%s", (ev["id"],))
                skipped.append(ev["id"])
                continue
            token = jwt.encode({"sub": "scripted-agent", "tenant": ev["tenant_id"], "role": "agent",
                                "exp": int(time.time()) + 300}, secret, algorithm="HS256")
            agent, started, status = make_agent(http, token, reader, model), time.monotonic(), "ok"
            try:
                agent.handle(ev)
                c.execute("UPDATE event_queue SET done_at=now() WHERE id=%s", (ev["id"],))
                done += 1
            except Exception as e:  # noqa: BLE001  retry later; after MAX_ATTEMPTS set the event aside, never block the others
                status = "failed"
                log.warning("event %s failed (attempt %s): %s: %s", ev["kind"], ev["id"], type(e).__name__, str(e)[:200])
                c.execute("UPDATE event_queue SET attempts=attempts+1, claimed_at=NULL, "
                          "available_at=now()+%s::interval, dead_at=CASE WHEN attempts+1>=%s THEN now() END "
                          "WHERE id=%s", (RETRY_AFTER, MAX_ATTEMPTS, ev["id"]))
                skipped.append(ev["id"])  # not again in this drain
            finally:
                c.execute(
                    "INSERT INTO agent_run (tenant_id, invoice_id, runner, model, tokens_in, tokens_out, "
                    "tool_calls, started_at, duration_ms, status) VALUES (%s,%s,%s,%s,%s,%s,%s,now(),%s,%s)",
                    (ev["tenant_id"], ev["invoice_id"], agent.runner, agent.model_name, agent.tokens_in,
                     agent.tokens_out, agent.tool_calls, int((time.monotonic() - started) * 1000), status))
                c.execute(UNLOCK, (ev["invoice_id"],))
    return done


if __name__ == "__main__":
    import httpx

    from hermes.ledger import db

    base = os.environ.get("HERMES_API_URL", "http://localhost:8000")
    secret = os.environ.get("HERMES_TOKEN_SECRET", "dev-only-secret-do-not-use-0123456789")
    dsn = db.database_url()
    print(drain(dsn, secret, httpx.Client(base_url=base)))
    with psycopg.connect(dsn, autocommit=True) as wc:  # run often: deliveries are due within seconds
        print(webhooks.deliver_due(wc, webhooks.signing_key(),
                                   os.environ.get("HERMES_ENV") == "development"))
