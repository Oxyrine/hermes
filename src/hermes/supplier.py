"""The supplier's own view of their invoices, in plain English. Every figure comes from invoice_view
(the engines); this only words it. Interest is left out when eligibility is `ineligible`."""

from datetime import date
from decimal import Decimal

from hermes.ledger import service

ADVICE = "This is information, not legal advice: ask your accountant or a lawyer before you decide."


def _on(iso: str) -> str:
    d = date.fromisoformat(iso)
    return f"{d.day} {d:%b}"


def _status(v: dict, as_of: date) -> str:
    if v["state"] == "closed":
        return "Paid and closed"
    dl = v["deadline"]
    if dl["status"] != "ok":
        return "Waiting for the buyer's acceptance to be fixed"
    due = date.fromisoformat(dl["due"])
    if as_of <= due:
        accepted = any(x["signal"] == "ims_accepted" for x in v["evidence"]["contributions"])
        return ("Buyer has accepted this in GST. " if accepted else "") + f"Payment due {_on(dl['due'])}"
    text = f"Overdue {(as_of - due).days} days"
    if v["eligibility"]["status"] != "ineligible" and v["claim"]:
        text += f"; interest so far \u20b9{v['claim']['interest']}"
    return text


def _cash(v: dict, rate: Decimal) -> dict | None:
    """The advance on offer and what it costs, shown before the supplier accepts."""
    pct = Decimal(v["collateral"]["advance_rate"]) if v["collateral"] else Decimal(0)
    if v["state"] == "closed" or v["eligibility"]["status"] == "ineligible" or pct == 0:
        return None
    advance = (Decimal(v["total"]) * pct).quantize(Decimal("0.01"))
    month = (advance * rate / 100 * 30 / 365).quantize(Decimal("0.01"))
    return {"advance": str(advance), "rate_percent": str(rate.normalize()),
            "cost": f"{rate.normalize():f}% a year on the advance, about \u20b9{month} for 30 days; "
                    "you pay nothing if you do not accept"}


def supplier_invoices(conn, tenant_id, supplier_id, as_of: date) -> list[dict]:
    rate = conn.execute("SELECT lender_rate_nominal FROM tenant WHERE id=%s", (tenant_id,)).fetchone()[0]
    out = []
    for row in service.list_invoices(conn, tenant_id, supplier_id):
        v = service.invoice_view(conn, tenant_id, row["id"], as_of)
        out.append({
            "id": row["id"], "invoice_no": row["invoice_no"], "total": row["total"],
            "status": _status(v, as_of), "cash": _cash(v, rate),
            "rule": f"Deadline rule {v['deadline']['rule_version']}; eligibility rule "
                    f"{v['eligibility']['rule_version']}",
            "advice": ADVICE})
    return out
