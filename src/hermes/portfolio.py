"""The lender's overview: portfolio rows, buyer view, watchlist and alerts. Every figure comes from
invoice_view (the engines); this only selects, counts and averages. Claim value (which includes
interest) is left out when eligibility is `ineligible`."""

import csv
import io
from datetime import date, timedelta
from decimal import Decimal

from psycopg.rows import dict_row

from hermes.ledger import service

COLUMNS = ["supplier", "buyer", "total", "state", "band", "days_late", "claim_value", "exposure",
           "ltv", "alerts"]
RATE_WINDOW_DAYS = 30  # a bank-rate change stays an alert this long after it takes effect
MESSAGES = {"hard_flag": "Hard flag on the evidence", "ltv_breach": "Loan-to-value above the band limit",
            "cushion": "Lender rate is above three times the bank rate: the cushion shrinks with time"}


def _scan(conn, tenant, as_of: date):
    """(rows, alerts) for every invoice in the tenant, one invoice_view each."""
    cur = conn.cursor(row_factory=dict_row)
    watched = {str(r[0]) for r in conn.execute("SELECT buyer_id FROM buyer_watch WHERE tenant_id=%s", (tenant,))}
    rows, alerts = [], []
    for i in cur.execute(
            "SELECT i.id::text, i.invoice_no, i.buyer_id::text, s.legal_name AS supplier, "
            "b.legal_name AS buyer FROM invoice i JOIN supplier s ON s.id=i.supplier_id "
            "JOIN buyer b ON b.id=i.buyer_id WHERE i.tenant_id=%s ORDER BY i.invoice_no", (tenant,)).fetchall():
        v = service.invoice_view(conn, tenant, i["id"], as_of)
        col, dl = v["collateral"], v["deadline"]
        due = dl.get("due") if dl["status"] == "ok" else None
        kinds = []
        if v["state"] != "closed":
            if v["evidence"]["hard_flags"]:
                kinds.append("hard_flag")
            if col and "ltv_above_band_limit" in col["alerts"]:
                kinds.append("ltv_breach")
            if col and "cushion erodes with time" in col["alerts"]:
                kinds.append("cushion")
        rows.append({
            "id": i["id"], "invoice_no": i["invoice_no"], "buyer_id": i["buyer_id"],
            "supplier": i["supplier"], "buyer": i["buyer"], "total": v["total"], "state": v["state"],
            "band": v["evidence"]["band"], "eligibility": v["eligibility"]["status"],
            "days_late": max(0, (as_of - date.fromisoformat(due)).days) if due else None,
            "claim_value": v["claim"]["claim_value"] if v["claim"] and v["eligibility"]["status"] != "ineligible" else None,
            "exposure": col and col["exposure"], "ltv": col and col["ltv"],
            "accepted": any(c["signal"] == "ims_accepted" for c in v["evidence"]["contributions"]),
            "watchlist": i["buyer_id"] in watched, "alerts": kinds,
            "sources": {k: v["sources"].get(k) for k in ("total", "band", "due", "claim_value", "exposure", "ltv")}})
        alerts += [{"key": f"{k}:{i['id']}", "kind": k, "invoice_id": i["id"], "invoice_no": i["invoice_no"],
                    "buyer": i["buyer"], "message": MESSAGES[k]} for k in kinds]
    for r in conn.execute("SELECT effective_from, rate FROM bank_rate WHERE approved_by IS NOT NULL "
                          "AND effective_from BETWEEN %s AND %s", (as_of - timedelta(RATE_WINDOW_DAYS), as_of)):
        alerts.append({"key": f"bank_rate_change:{r[0]}", "kind": "bank_rate_change", "invoice_id": None,
                       "invoice_no": None, "buyer": None,
                       "message": f"Bank rate is {r[1].normalize():f}% from {r[0]}"})
    return rows, alerts


def _matches(r, state, band, buyer):
    return all(want is None or r[k] == want for k, want in (("state", state), ("band", band), ("buyer_id", buyer)))


def portfolio(conn, tenant, as_of, state=None, band=None, buyer=None) -> list[dict]:
    return [r for r in _scan(conn, tenant, as_of)[0] if _matches(r, state, band, buyer)]


def portfolio_csv(rows: list[dict]) -> str:
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(COLUMNS)
    for r in rows:
        w.writerow(";".join(r[c]) if c == "alerts" else "" if r[c] is None else r[c] for c in COLUMNS)
    return out.getvalue()


def buyer_view(conn, tenant, buyer_id, as_of: date) -> dict:
    rows = [r for r in _scan(conn, tenant, as_of)[0] if r["buyer_id"] == buyer_id]
    if not rows:
        raise service.NotFound("buyer")
    late = [r["days_late"] for r in rows if r["days_late"] is not None]
    return {
        "id": buyer_id, "buyer": rows[0]["buyer"], "watchlist": rows[0]["watchlist"], "invoices": rows,
        "share_accepted": str((Decimal(sum(r["accepted"] for r in rows)) / len(rows)).quantize(Decimal("0.01"))),
        # ponytail: open and closed invoices alike count by their days late at as_of
        "average_days_late": str((Decimal(sum(late)) / len(late)).quantize(Decimal("0.1"))) if late else None}


def set_watch(conn, tenant, buyer_id, user_id, on: bool) -> dict:
    if not conn.execute("SELECT 1 FROM invoice WHERE tenant_id=%s AND buyer_id::text=%s LIMIT 1",
                        (tenant, buyer_id)).fetchone():
        raise service.NotFound("buyer")
    if on:
        conn.execute("INSERT INTO buyer_watch (tenant_id, buyer_id, added_by) VALUES (%s,%s,%s) "
                     "ON CONFLICT DO NOTHING", (tenant, buyer_id, user_id))
    else:
        conn.execute("DELETE FROM buyer_watch WHERE tenant_id=%s AND buyer_id::text=%s", (tenant, buyer_id))
    return {"buyer_id": buyer_id, "watchlist": on}


def alert_list(conn, tenant, as_of) -> list[dict]:
    state = {r[0]: r[1:] for r in conn.execute(
        "SELECT s.key, a.email, s.acknowledged_at::text, t.email FROM alert_state s "
        "LEFT JOIN app_user a ON a.id=s.acknowledged_by LEFT JOIN app_user t ON t.id=s.assigned_to "
        "WHERE s.tenant_id=%s", (tenant,))}
    return [a | dict(zip(("acknowledged_by", "acknowledged_at", "assigned_to"), state.get(a["key"], (None,) * 3)))
            for a in _scan(conn, tenant, as_of)[1]]


def work_alert(conn, tenant, as_of, key, user_id, assignee=None) -> dict:
    """Acknowledge (assignee None) or assign a current alert; unknown keys are not found."""
    if key not in {a["key"] for a in _scan(conn, tenant, as_of)[1]}:
        raise service.NotFound("alert")
    if assignee is None:
        conn.execute(
            "INSERT INTO alert_state (tenant_id, key, acknowledged_by, acknowledged_at) VALUES (%s,%s,%s,now()) "
            "ON CONFLICT (tenant_id, key) DO UPDATE SET acknowledged_by=%s, acknowledged_at=now()",
            (tenant, key, user_id, user_id))
    else:
        row = conn.execute("SELECT id FROM app_user WHERE tenant_id=%s AND email=%s AND role IN "
                           "('lender_ops','lender_approver')", (tenant, assignee)).fetchone()
        if row is None:
            raise ValueError("assignee must be a lender user in this tenant")
        conn.execute("INSERT INTO alert_state (tenant_id, key, assigned_to) VALUES (%s,%s,%s) "
                     "ON CONFLICT (tenant_id, key) DO UPDATE SET assigned_to=%s", (tenant, key, row[0], row[0]))
    return {"key": key}
