"""Ledger operations: storing engine runs and assembling the invoice read from engine outputs.

Every query takes the caller's tenant id and filters by it.
"""

import json
from datetime import date
from decimal import Decimal
from uuid import UUID

from psycopg.rows import dict_row

from hermes.engines import collateral, deadline, eligibility, evidence, interest, settlement
from hermes.engines.common import canonical_json

ENGINES = {
    "collateral": collateral.run, "deadline": deadline.run, "eligibility": eligibility.run,
    "evidence": evidence.run, "interest": interest.run, "settlement": settlement.run,
}
CENT = Decimal("0.01")


class NotFound(Exception):
    pass


def fy_of(d: date) -> str:
    y = d.year if d.month >= 4 else d.year - 1
    return f"{y}-{(y + 1) % 100:02d}"


def run_engine(conn, tenant_id, invoice_id, engine: str, inputs: dict, *, reuse: bool = False):
    """Run an engine and store the run (rule version, inputs hash, inputs, outputs).

    With reuse, an identical stored run (same rule version and inputs hash) is not stored again.
    """
    if engine not in ENGINES:
        raise NotFound(engine)
    try:
        invoice_id = None if invoice_id is None else str(UUID(str(invoice_id)))
    except ValueError:
        raise NotFound("invoice") from None
    if invoice_id is not None and not conn.execute(
        "SELECT 1 FROM invoice WHERE id=%s AND tenant_id=%s", (invoice_id, tenant_id)
    ).fetchone():
        raise NotFound("invoice")
    out = ENGINES[engine](inputs)
    if reuse and conn.execute(
        "SELECT 1 FROM engine_run WHERE tenant_id=%s AND invoice_id IS NOT DISTINCT FROM %s "
        "AND engine=%s AND rule_version=%s AND inputs_hash=%s",
        (tenant_id, invoice_id, engine, out["rule_version"], out["input_hash"]),
    ).fetchone():
        return out
    conn.execute(
        "INSERT INTO engine_run (tenant_id, invoice_id, engine, rule_version, inputs_hash, "
        "inputs, outputs) VALUES (%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb)",
        (tenant_id, invoice_id, engine, out["rule_version"], out["input_hash"],
         canonical_json(inputs), json.dumps(out)),
    )
    return out


def list_invoices(conn, tenant_id) -> list[dict]:
    rows = conn.cursor(row_factory=dict_row).execute(
        "SELECT id::text, invoice_no, total::text, state FROM invoice WHERE tenant_id=%s "
        "ORDER BY invoice_no", (tenant_id,)).fetchall()
    return rows


def _section(env: dict, **fields) -> dict:
    return {**fields, "rule_version": env["rule_version"], "reasons": env["reasons"]}


def invoice_view(conn, tenant_id, invoice_id, as_of: date) -> dict:
    try:
        invoice_id = str(UUID(str(invoice_id)))
    except ValueError:
        raise NotFound("invoice") from None
    cur = conn.cursor(row_factory=dict_row)
    inv = cur.execute("SELECT i.*, t.lender_rate_nominal FROM invoice i JOIN tenant t "
                      "ON t.id=i.tenant_id WHERE i.id=%s AND i.tenant_id=%s",
                      (invoice_id, tenant_id)).fetchone()
    if inv is None:
        raise NotFound("invoice")
    sup = cur.execute("SELECT * FROM supplier WHERE id=%s AND tenant_id=%s",
                      (inv["supplier_id"], tenant_id)).fetchone()
    con = cur.execute("SELECT * FROM contract WHERE id=%s AND tenant_id=%s",
                      (inv["contract_id"], tenant_id)).fetchone()
    grn = cur.execute("SELECT extracted FROM document WHERE invoice_id=%s AND tenant_id=%s "
                      "AND doc_type='grn' ORDER BY id LIMIT 1", (invoice_id, tenant_id)).fetchone()
    cls = cur.execute("SELECT class FROM udyam_classification WHERE supplier_id=%s AND fy=%s "
                      "AND tenant_id=%s", (sup["id"], fy_of(con["signed_date"]), tenant_id)).fetchone()
    items = cur.execute("SELECT signal, source_ref FROM evidence_item WHERE invoice_id=%s AND "
                        "tenant_id=%s ORDER BY detected_at, id", (invoice_id, tenant_id)).fetchall()
    pays = cur.execute("SELECT paid_on, amount FROM payment WHERE invoice_id=%s AND tenant_id=%s "
                       "ORDER BY paid_on", (invoice_id, tenant_id)).fetchall()
    rates = cur.execute("SELECT effective_from, rate FROM bank_rate WHERE approved_by IS NOT NULL "
                        "ORDER BY effective_from").fetchall()
    adv = cur.execute("SELECT principal, disbursed_on FROM advance WHERE invoice_id=%s AND "
                      "tenant_id=%s ORDER BY disbursed_on LIMIT 1", (invoice_id, tenant_id)).fetchone()

    def run(engine, inputs):
        return run_engine(conn, tenant_id, invoice_id, engine, inputs, reuse=True)

    delivery = grn["extracted"]["delivery_date"]
    elig = run("eligibility", {
        "udyam_urn": sup["udyam_urn"], "registration_date": sup["udyam_reg_date"].isoformat(),
        "enterprise_type": sup["enterprise_type"], "classification": cls["class"] if cls else None,
        "contract_date": con["signed_date"].isoformat(), "supply_date": delivery})
    dl_in = {"delivery": delivery, "written_days": con["written_payment_days"]}
    dl = run("deadline", dl_in)
    ev = run("evidence", {"as_of": as_of.isoformat(), "signals": [
        {"type": i["signal"], "source": i["source_ref"]} for i in items]})

    out = {
        "id": str(invoice_id), "invoice_no": inv["invoice_no"], "total": str(inv["total"]),
        "state": inv["state"],
        "eligibility": _section(elig, status=elig["result"]["status"],
                                detail=elig["result"]["reasons"]),
        "deadline": _section(dl, **dl["result"]),
        "evidence": _section(ev, **ev["result"]),
        "claim": None, "collateral": None,
    }
    if dl["result"]["status"] != "ok":
        return out

    paid = [{"date": p["paid_on"].isoformat(), "amount": str(p["amount"])} for p in pays]
    unpaid = inv["total"] - sum((p["amount"] for p in pays if p["paid_on"] <= as_of), Decimal(0))
    bank_rate = next((str(r["rate"]) for r in reversed(rates) if r["effective_from"] <= as_of), None)
    interest_from = date.fromisoformat(dl["result"]["interest_from"])
    stat = None
    if as_of >= interest_from:
        stat = run("interest", {
            "principal": str(inv["total"]), "interest_start": interest_from.isoformat(),
            "as_of": as_of.isoformat(), "part_payments": paid,
            "bank_rates": [{"effective_from": r["effective_from"].isoformat(),
                            "rate_percent": str(r["rate"])} for r in rates]})
    col_in = {
        "eligibility": elig["result"]["status"], "band": ev["result"]["band"],
        "principal": str(inv["total"]), "payments": paid, "due_date": dl["result"]["due"],
        "as_of": as_of.isoformat(), "statutory_claim": stat["result"]["claim"] if stat else "0",
        "lender_rate_percent": str(inv["lender_rate_nominal"]), "bank_rate_percent": bank_rate,
    }
    if adv:
        col_in |= {"advance": str(adv["principal"]), "funded_on": adv["disbursed_on"].isoformat()}
    col = run("collateral", col_in)
    cr = col["result"]
    claim_value = Decimal(cr["claim_display"])
    out["claim"] = _section(
        stat or col, as_of=as_of.isoformat(), principal=str(unpaid.quantize(CENT)),
        interest=str((claim_value - unpaid).quantize(CENT)), claim_value=cr["claim_display"])
    out["collateral"] = _section(col, exposure=cr["exposure_display"], ltv=cr["ltv"],
                                 advance_rate=cr["advance_rate"], alerts=cr["alerts"])
    return out
