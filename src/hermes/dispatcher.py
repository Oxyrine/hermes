"""Event dispatcher: claims one event at a time, takes a per-invoice lock, runs the agent,
releases. The lock is a Postgres advisory lock on the invoice id (session-level, so the agent's
own API calls, on other connections, are not blocked). `python -m hermes.dispatcher` drains the
queue against a running API (HERMES_API_URL)."""

import os
import time

import jwt
import psycopg
from psycopg.rows import dict_row

from hermes import webhooks
from hermes.agent import ScriptedAgent

CLAIM = (
    "UPDATE event_queue SET claimed_at=now() WHERE id=(SELECT id FROM event_queue WHERE "
    "done_at IS NULL AND claimed_at IS NULL AND available_at<=now() AND id <> ALL(%s) "
    "ORDER BY id FOR UPDATE SKIP LOCKED LIMIT 1) "
    "RETURNING id, tenant_id::text, invoice_id::text, kind, payload")
LOCK = "SELECT pg_try_advisory_lock(hashtext(%s))"
UNLOCK = "SELECT pg_advisory_unlock(hashtext(%s))"


def drain(dsn: str, secret: str, http) -> int:
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
            agent, started, status = ScriptedAgent(http, token), time.monotonic(), "ok"
            try:
                agent.handle(ev)
                c.execute("UPDATE event_queue SET done_at=now() WHERE id=%s", (ev["id"],))
                done += 1
            except Exception:
                status = "failed"
                raise
            finally:
                c.execute(
                    "INSERT INTO agent_run (tenant_id, invoice_id, runner, tool_calls, started_at, "
                    "duration_ms, status) VALUES (%s,%s,'scripted',%s,now(),%s,%s)",
                    (ev["tenant_id"], ev["invoice_id"], agent.tool_calls,
                     int((time.monotonic() - started) * 1000), status))
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
