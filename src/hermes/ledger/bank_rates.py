"""Bank-rate admin: a rate is entered by one operations user and used only once a different one
approves it (the table's CHECK also enforces that the two differ). Approval emits
`bank_rate.changed`, queued once per overdue invoice."""

import json
from datetime import date
from decimal import Decimal

from psycopg.rows import dict_row

from hermes.ledger import states
from hermes.ledger.service import NotFound, today


def list_rates(conn) -> list[dict]:
    return conn.cursor(row_factory=dict_row).execute(
        "SELECT effective_from::text, rate::text, source_url, entered_by::text, approved_by::text, "
        "CASE WHEN approved_by IS NULL THEN 'pending' ELSE 'approved' END AS status "
        "FROM bank_rate ORDER BY effective_from").fetchall()


def enter(conn, user_id: str, effective_from: date, rate: str, source_url: str) -> dict:
    if not source_url.strip():
        raise ValueError("a source link is required")
    if not Decimal(0) < Decimal(rate) < Decimal(100):
        raise ValueError("rate must be a percent between 0 and 100")
    if conn.execute("SELECT 1 FROM bank_rate WHERE effective_from=%s", (effective_from,)).fetchone():
        raise states.Refused("a rate is already entered for that date")
    conn.execute("INSERT INTO bank_rate (effective_from, rate, source_url, entered_by) "
                 "VALUES (%s,%s,%s,%s)", (effective_from, rate, source_url, user_id))
    conn.execute("INSERT INTO audit_log (actor, action, object_type, after) VALUES "
                 "(%s,'bank_rate_entered','bank_rate',%s::jsonb)",
                 (f"user:{user_id}", json.dumps({"effective_from": str(effective_from), "rate": rate})))
    return {"effective_from": str(effective_from), "status": "pending"}


def approve(conn, user_id: str, effective_from: date) -> dict:
    row = conn.execute("SELECT entered_by::text, approved_by FROM bank_rate WHERE effective_from=%s",
                       (effective_from,)).fetchone()
    if row is None:
        raise NotFound("rate")
    if row[1] is not None:
        raise states.Refused("already approved")
    if row[0] == user_id:
        raise states.Refused("the person who entered a rate cannot approve it")
    conn.execute("UPDATE bank_rate SET approved_by=%s WHERE effective_from=%s", (user_id, effective_from))
    conn.execute("INSERT INTO audit_log (actor, action, object_type, after) VALUES "
                 "(%s,'bank_rate_approved','bank_rate',%s::jsonb)",
                 (f"user:{user_id}", json.dumps({"effective_from": str(effective_from)})))
    payload = json.dumps({"as_of": today(conn).isoformat(), "effective_from": str(effective_from)})
    queued = conn.execute(
        "INSERT INTO event_queue (tenant_id, invoice_id, kind, payload) "
        "SELECT tenant_id, id, 'bank_rate.changed', %s::jsonb FROM invoice WHERE state='overdue'",
        (payload,)).rowcount
    return {"effective_from": str(effective_from), "status": "approved", "events_queued": queued}
