"""Invoice state machine (product spec section 4). The only code that changes `invoice.state`.

TABLE maps (from, to) to a guard over a facts dict. Facts are computed server-side by the caller
(service.guard_facts); a guard whose fact is absent refuses.
"""

import json

from psycopg.rows import dict_row

TABLE = {
    ("ingested", "verified"): lambda f: bool(f.get("matched")),
    ("ingested", "needs_review"): lambda f: bool(f.get("low_confidence")),
    ("needs_review", "verified"): lambda f: bool(f.get("manual_review")),
    ("verified", "gst_blocked"): lambda f: bool(f.get("ims_blocked")),
    ("gst_blocked", "verified"): lambda f: bool(f.get("ims_accepted")),
    ("verified", "financeable"): lambda f: f.get("band") in ("A", "B", "C")
    and f.get("eligibility") not in (None, "ineligible"),
    ("financeable", "advanced"): lambda f: bool(f.get("has_advance")),
    ("advanced", "overdue"): lambda f: bool(f.get("unpaid") and f.get("past_due")),
    ("verified", "overdue"): lambda f: bool(f.get("unpaid") and f.get("past_due")),
    ("financeable", "overdue"): lambda f: bool(f.get("unpaid") and f.get("past_due")),
    ("overdue", "settlement_offered"): lambda f: bool(f.get("approved_action")),
    ("settlement_offered", "odr_ready"): lambda f: bool(f.get("supplier_consent")),
    ("odr_ready", "odr_filed"): lambda f: bool(f.get("case_number")),
    ("odr_filed", "awarded"): lambda f: bool(f.get("award_document")),
    ("paid", "closed"): lambda f: bool(f.get("lender_confirmed")),
}
STATES = {s for pair in TABLE for s in pair}
for _s in STATES - {"paid", "closed"}:  # any open state -> paid
    TABLE[(_s, "paid")] = lambda f: bool(f.get("covered"))


class Refused(Exception):
    pass


def transition(conn, tenant_id, invoice_id, to: str, facts: dict, actor: str) -> None:
    with conn.transaction():
        row = conn.cursor(row_factory=dict_row).execute(
            "SELECT state FROM invoice WHERE id=%s AND tenant_id=%s FOR UPDATE",
            (invoice_id, tenant_id)).fetchone()
        if row is None:
            raise Refused("invoice not found")
        guard = TABLE.get((row["state"], to))
        if guard is None:
            raise Refused(f"no transition {row['state']} -> {to}")
        if not guard(facts):
            raise Refused(f"guard failed for {row['state']} -> {to}")
        conn.execute("UPDATE invoice SET state=%s, state_changed_at=now() WHERE id=%s",
                     (to, invoice_id))
        conn.execute(
            "INSERT INTO audit_log (tenant_id, actor, action, object_type, object_id, before, after) "
            "VALUES (%s,%s,'state_change','invoice',%s,%s::jsonb,%s::jsonb)",
            (tenant_id, actor, invoice_id, json.dumps({"state": row["state"]}),
             json.dumps({"state": to})))
