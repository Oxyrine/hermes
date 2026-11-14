"""The buyer statement: a signed, expiring, read-only link to one invoice. The token carries the
tenant and invoice and no role, so it is useless as an API login and an API token is useless here."""

import json
import re
import time
from datetime import date

import jwt
from psycopg.rows import dict_row

from hermes.ledger import service

LINK_TTL_SECONDS = 30 * 24 * 3600
NOTES = (
    ("A payment to a micro or small enterprise made after the statutory period defers the "
    "buyer's income-tax deduction for that amount until it is paid."),
    ("Where an award is made and challenged, a deposit of 75% of the awarded amount is required "
    "before the challenge is heard."),
)
CHOICES = ("will_pay", "dispute", "contact_me")
BANNED = re.compile(r"\b(legal action|sue|lawsuit|prosecut\w*|criminal|penalt\w*|liable|"
                    r"you must|you will be|we will take|final warning|guilty|illegal|unlawful|"
                    r"in breach|breach of)\b", re.IGNORECASE)


class Refused(Exception):
    """The link is not valid; the reason is never shown."""


def make_token(secret: str, tenant_id: str, invoice_id: str, now: float | None = None) -> str:
    now = time.time() if now is None else now
    return jwt.encode({"typ": "statement", "tenant": str(tenant_id), "inv": str(invoice_id),
                       "exp": int(now) + LINK_TTL_SECONDS}, secret, algorithm="HS256")


def open_token(secret: str, token: str) -> tuple[str, str]:
    try:
        c = jwt.decode(token, secret, algorithms=["HS256"],
                       options={"require": ["tenant", "inv", "exp", "typ"]})
    except jwt.InvalidTokenError:
        raise Refused from None
    if c["typ"] != "statement":
        raise Refused
    return c["tenant"], c["inv"]


def _audit(conn, tenant, inv, action, after=None):
    conn.execute("INSERT INTO audit_log (tenant_id, actor, action, object_type, object_id, after) "
                 "VALUES (%s,'buyer_link',%s,'invoice',%s,%s::jsonb)",
                 (tenant, action, inv, json.dumps(after or {})))


def statement(conn, secret: str, token: str) -> dict:
    tenant, inv = open_token(secret, token)
    as_of = service.today(conn)
    try:
        v = service.invoice_view(conn, tenant, inv, as_of)
    except service.NotFound:
        raise Refused from None
    if v["claim"] is None:
        raise Refused
    cur = conn.cursor(row_factory=dict_row)
    names = cur.execute(
        "SELECT i.invoice_date::text, i.invoice_no, s.legal_name AS supplier, b.legal_name AS buyer "
        "FROM invoice i JOIN supplier s ON s.id=i.supplier_id JOIN buyer b ON b.id=i.buyer_id "
        "WHERE i.id=%s", (inv,)).fetchone()
    grn = cur.execute("SELECT extracted FROM document WHERE invoice_id=%s AND doc_type='grn' "
                      "ORDER BY id LIMIT 1", (inv,)).fetchone()
    signals = [r["signal"] for r in cur.execute(
        "SELECT signal FROM evidence_item WHERE invoice_id=%s ORDER BY detected_at, id", (inv,))]
    due = date.fromisoformat(v["deadline"]["due"])
    _audit(conn, tenant, inv, "statement_opened")
    return {
        "invoice": {"invoice_no": names["invoice_no"], "invoice_date": names["invoice_date"],
                    "total": v["total"], "supplier": names["supplier"], "buyer": names["buyer"]},
        "delivery_evidence": {"delivery_date": grn["extracted"]["delivery_date"] if grn else None,
                              "signals": signals},
        "acceptance_date": v["deadline"]["acceptance"], "due_date": v["deadline"]["due"],
        "as_of": as_of.isoformat(), "days_late": max((as_of - due).days, 0),
        "interest_to_date": v["claim"]["interest"], "amount_with_interest": v["claim"]["claim_value"],
        "notes": list(NOTES), "choices": list(CHOICES),
    }


def respond(conn, secret: str, token: str, choice: str, note: str | None) -> dict:
    tenant, inv = open_token(secret, token)
    if choice not in CHOICES:
        raise ValueError("unknown choice")
    payload = {"choice": choice, "note": (note or "")[:1000]}
    with conn.transaction():
        conn.execute("INSERT INTO event_queue (tenant_id, invoice_id, kind, payload, done_at) "
                     "VALUES (%s,%s,'buyer.responded',%s::jsonb, now())",  # informational: no agent step
                     (tenant, inv, json.dumps(payload)))
        _audit(conn, tenant, inv, "buyer_response", payload)
    return {"recorded": choice}
