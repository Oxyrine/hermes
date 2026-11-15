"""Ledger operations: storing engine runs and assembling the invoice read from engine outputs.

Every query takes the caller's tenant id and filters by it.
"""

import base64
import binascii
import hashlib
import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID
from zoneinfo import ZoneInfo

from psycopg.rows import dict_row

from hermes import letter, webhooks
from hermes.engines import collateral, deadline, eligibility, evidence, interest, settlement
from hermes.engines.common import canonical_json
from hermes.ledger import states

ENGINES = {
    "collateral": collateral.run, "deadline": deadline.run, "eligibility": eligibility.run,
    "evidence": evidence.run, "interest": interest.run, "settlement": settlement.run,
}
CENT = Decimal("0.01")
OFFER_DAYS = 7  # a settlement offer lapses this many days after it is drafted


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


def run_ref(conn, tenant_id, invoice_id, engine: str, input_hash: str) -> dict | None:
    """The source reference to a stored engine run: what a figure computed by it opens."""
    row = conn.execute(
        "SELECT id::text, rule_version, outputs->'reasons' FROM engine_run WHERE tenant_id=%s AND "
        "invoice_id IS NOT DISTINCT FROM %s AND engine=%s AND inputs_hash=%s "
        "ORDER BY run_at DESC LIMIT 1", (tenant_id, invoice_id, engine, input_hash)).fetchone()
    return row and {"kind": "engine_run", "id": row[0], "engine": engine, "rule_version": row[1],
                    "input_hash": input_hash,
                    "provisional": any("Awaiting legal review" in r for r in row[2] or [])}


def _field_ref(doc: dict | None, field: str) -> dict | None:
    """Where an extracted value was read: the document, page and quote."""
    if doc is None:
        return None
    srcs = doc["extracted"].get("sources") or {}
    s = srcs.get(field) or (srcs.get(f"{doc['doc_type']}_date") if field == "delivery_date" else None) or {}
    return {"kind": "document", "id": doc["id"], "doc_type": doc["doc_type"], "field": field,
            "page": s.get("page"), "quote": s.get("quote")}


def list_invoices(conn, tenant_id, supplier_id=None) -> list[dict]:
    return conn.cursor(row_factory=dict_row).execute(
        "SELECT id::text, invoice_no, total::text, state FROM invoice WHERE tenant_id=%s "
        "AND (%s::text IS NULL OR supplier_id::text=%s) ORDER BY invoice_no",
        (tenant_id, supplier_id, supplier_id)).fetchall()


def receipts(conn, tenant_id, invoice_id) -> list[dict]:
    """Bank receipts recorded against an invoice (sensitive: the caller audits the read)."""
    inv = _owned(conn, tenant_id, invoice_id)
    return conn.cursor(row_factory=dict_row).execute(
        "SELECT id::text, amount::text, paid_on::text, utr, source FROM payment "
        "WHERE invoice_id=%s AND tenant_id=%s ORDER BY paid_on", (inv, tenant_id)).fetchall()


def documents(conn, tenant_id, invoice_id) -> list[dict]:
    """Documents attached to an invoice (sensitive: the caller audits the read)."""
    inv = _owned(conn, tenant_id, invoice_id)
    return conn.cursor(row_factory=dict_row).execute(
        "SELECT id::text, doc_type, extracted FROM document WHERE invoice_id=%s AND tenant_id=%s "
        "ORDER BY doc_type", (inv, tenant_id)).fetchall()


def _evidence_ref(source: dict | None, item_id: str | None) -> dict | None:
    """The record an evidence contribution came from: IMS event, document, payment, raw record,
    else the evidence item itself."""
    for key, kind in (("ims_event_id", "ims_event"), ("document_id", "document"),
                      ("payment_id", "payment"), ("raw_id", "raw_record")):
        if source and source.get(key):
            return {"kind": kind, "id": str(source[key])}
    return item_id and {"kind": "evidence_item", "id": item_id}


def _section(env: dict, **fields) -> dict:
    return {**fields, "rule_version": env["rule_version"], "reasons": env["reasons"]}


def _waterfall_row(cur, tenant_id, invoice_id):
    return cur.execute(
        "SELECT as_of::text, receipts::text, lender_exposure::text, costs::text, supplier::text, "
        "rule_version, input_hash FROM waterfall WHERE invoice_id=%s AND tenant_id=%s",
        (invoice_id, tenant_id)).fetchone()


def invoice_view(conn, tenant_id, invoice_id, as_of: date, env: dict | None = None) -> dict:
    """With env, the engine envelopes and collateral inputs used are also stored in it by name."""
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
    grn = cur.execute("SELECT id::text, doc_type, extracted FROM document WHERE invoice_id=%s AND tenant_id=%s "
                      "AND extracted->>'delivery_date' IS NOT NULL ORDER BY doc_type, id LIMIT 1",
                      (invoice_id, tenant_id)).fetchone()  # a challan's date first, then the GRN's
    idoc = cur.execute("SELECT id::text, doc_type, extracted FROM document WHERE invoice_id=%s AND "
                       "tenant_id=%s AND doc_type='invoice' AND extracted IS NOT NULL ORDER BY id "
                       "LIMIT 1", (invoice_id, tenant_id)).fetchone()
    cls = cur.execute("SELECT class FROM udyam_classification WHERE supplier_id=%s AND fy=%s "
                      "AND tenant_id=%s", (sup["id"], fy_of(con["signed_date"]), tenant_id)).fetchone()
    items = cur.execute("SELECT id::text, signal, source_ref, value FROM evidence_item WHERE invoice_id=%s AND "
                        "tenant_id=%s ORDER BY detected_at, id", (invoice_id, tenant_id)).fetchall()
    last_ims = max((n for n, i in enumerate(items) if i["signal"].startswith("ims_")), default=None)
    items = [i for n, i in enumerate(items) if not i["signal"].startswith("ims_") or n == last_ims]
    pays = cur.execute("SELECT paid_on, amount FROM payment WHERE invoice_id=%s AND tenant_id=%s "
                       "ORDER BY paid_on", (invoice_id, tenant_id)).fetchall()
    rates = cur.execute("SELECT effective_from, rate FROM bank_rate WHERE approved_by IS NOT NULL "
                        "ORDER BY effective_from").fetchall()
    adv = cur.execute("SELECT principal, disbursed_on FROM advance WHERE invoice_id=%s AND "
                      "tenant_id=%s ORDER BY disbursed_on LIMIT 1", (invoice_id, tenant_id)).fetchone()

    flags = cur.execute("SELECT kind, flagged_on FROM hard_flag_event WHERE invoice_id=%s AND "
                        "tenant_id=%s ORDER BY id", (invoice_id, tenant_id)).fetchall()

    env = {} if env is None else env
    runs: dict = {}

    def run(engine, inputs):
        env[engine] = run_engine(conn, tenant_id, invoice_id, engine, inputs, reuse=True)
        runs[engine] = run_ref(conn, tenant_id, invoice_id, engine, env[engine]["input_hash"])
        return env[engine]

    delivery = grn["extracted"]["delivery_date"]
    # figure -> source reference: extracted values open a document page and quote, computed ones an engine run
    refs: dict = {}
    inv_ref = {"kind": "invoice", "id": invoice_id}
    for f in ("total", "invoice_no"):
        refs[f] = _field_ref(idoc, f) if idoc and f in idoc["extracted"] else inv_ref
    refs["delivery_date"] = _field_ref(grn, "delivery_date")
    if con["terms_source"]:
        refs["written_days"] = {"kind": "contract", "id": str(con["id"]),
                                "page": con["terms_source"].get("page"),
                                "quote": con["terms_source"].get("quote")}
    elig = run("eligibility", {
        "udyam_urn": sup["udyam_urn"], "registration_date": sup["udyam_reg_date"].isoformat(),
        "enterprise_type": sup["enterprise_type"], "classification": cls["class"] if cls else None,
        "contract_date": con["signed_date"].isoformat(), "supply_date": delivery})
    dl_in = {"delivery": delivery, "written_days": con["written_payment_days"]}
    dl = run("deadline", dl_in)
    ev = run("evidence", {"as_of": as_of.isoformat(), "signals": [
        {"type": i["signal"], "source": i["source_ref"], **(i["value"] or {})} for i in items]})

    out = {
        "id": str(invoice_id), "invoice_no": inv["invoice_no"], "total": str(inv["total"]),
        "state": inv["state"], "waterfall": _waterfall_row(cur, tenant_id, invoice_id),
        "eligibility": _section(elig, status=elig["result"]["status"],
                                detail=elig["result"]["reasons"]),
        "deadline": _section(dl, **dl["result"]),
        "evidence": _section(ev, **ev["result"]),
        "hard_flags": [{"kind": f["kind"], "flagged_on": f["flagged_on"].isoformat()} for f in flags],
        "needs_review": ev["result"]["needs_review"] or bool(flags),
        "claim": None, "collateral": None, "sources": refs, "delivery_date": delivery,
    }
    ids = {(i["signal"], canonical_json(i["source_ref"])): i["id"] for i in items}
    # each contribution opens its own source record; copies, so the stored engine result is untouched
    out["evidence"]["contributions"] = [
        {**x, "ref": _evidence_ref(x["source"], ids.get((x["signal"], canonical_json(x["source"]))))}
        for x in out["evidence"]["contributions"]]
    refs |= {"eligibility": runs["eligibility"], "acceptance": runs["deadline"],
             "due": runs["deadline"], "interest_from": runs["deadline"],
             "score": runs["evidence"], "band": runs["evidence"]}
    if out["waterfall"]:
        refs["waterfall"] = run_ref(conn, tenant_id, invoice_id, "collateral",
                                    out["waterfall"]["input_hash"])
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
    col_in["hard_flags"] = [{"date": f["flagged_on"].isoformat(), "kind": f["kind"]} for f in flags]
    if adv:
        col_in |= {"advance": str(adv["principal"]), "funded_on": adv["disbursed_on"].isoformat()}
    env["collateral_inputs"] = col_in
    col = run("collateral", col_in)
    cr = col["result"]
    claim_value = Decimal(cr["claim_display"])
    out["claim"] = _section(
        stat or col, as_of=as_of.isoformat(), principal=str(unpaid.quantize(CENT)),
        interest=str((claim_value - unpaid).quantize(CENT)), claim_value=cr["claim_display"])
    refs |= {k: runs["interest"] if stat else runs["collateral"]
             for k in ("principal", "interest", "claim_value")}
    refs |= {k: runs["collateral"] for k in ("exposure", "ltv")}
    out["collateral"] = _section(col, exposure=cr["exposure_display"], ltv=cr["ltv"],
                                 advance_rate=cr["advance_rate"], alerts=cr["alerts"])
    return out


def raise_hard_flag(conn, tenant_id, invoice_id, kind: str, detail: dict | None = None) -> bool:
    """A hard flag on a funded invoice (IMS rejection, debit note, confirmed objection): record it
    for the lender and wake the agent, which re-reads the invoice and proposes a review. An
    unfunded invoice has no lender to tell, so nothing is recorded. Returns whether it was."""
    if not conn.execute("SELECT 1 FROM advance WHERE invoice_id=%s AND tenant_id=%s",
                        (invoice_id, tenant_id)).fetchone():
        return False
    d = today(conn)
    flag_id = conn.execute(
        "INSERT INTO hard_flag_event (tenant_id, invoice_id, kind, flagged_on, detail) "
        "VALUES (%s,%s,%s,%s,%s::jsonb) RETURNING id",
        (tenant_id, invoice_id, kind, d, json.dumps(detail or {}))).fetchone()[0]
    webhooks.publish(conn, tenant_id, "invoice.hard_flag",
                     {"invoice_id": str(invoice_id), "flag_id": flag_id})
    conn.execute("INSERT INTO event_queue (tenant_id, invoice_id, kind, payload) "
                 "VALUES (%s,%s,'invoice.hard_flag',%s::jsonb)",
                 (tenant_id, invoice_id, json.dumps({"flag": kind, "as_of": d.isoformat()})))
    return True


def today(conn) -> date:
    """The injected clock; the real IST date when none is set."""
    row = conn.execute("SELECT today FROM clock").fetchone()
    return row[0] if row else datetime.now(ZoneInfo("Asia/Kolkata")).date()


def set_clock(conn, d: date) -> None:
    conn.execute("INSERT INTO clock (today) VALUES (%s) ON CONFLICT (id) DO UPDATE SET today=%s",
                 (d, d))


def guard_facts(conn, tenant_id, invoice_id, as_of: date) -> dict:
    """Facts the state machine's guards read, computed here so callers cannot supply them."""
    view = invoice_view(conn, tenant_id, invoice_id, as_of)
    gst = gst_facts(conn, tenant_id, view["id"])
    row = conn.execute(
        "SELECT i.total - COALESCE((SELECT sum(amount) FROM payment WHERE invoice_id=i.id "
        "AND paid_on<=%s),0), i.due_date, EXISTS(SELECT 1 FROM advance WHERE invoice_id=i.id) "
        "FROM invoice i WHERE i.id=%s AND i.tenant_id=%s", (as_of, view["id"], tenant_id)).fetchone()
    unpaid, due, has_advance = row
    # amount due: the approved settlement offer if there is one, else the invoice total
    owed = conn.execute(
        "SELECT COALESCE((SELECT (draft->>'offer')::numeric FROM action_request WHERE invoice_id=%s "
        "AND kind='settlement_offer' AND status='approved'), (SELECT total FROM invoice WHERE id=%s))",
        (view["id"], view["id"])).fetchone()[0]
    received = conn.execute("SELECT COALESCE(sum(amount),0) FROM payment WHERE invoice_id=%s "
                            "AND paid_on<=%s", (view["id"], as_of)).fetchone()[0]
    covered = received >= owed
    return {"ims_blocked": gst["blocked"], "ims_accepted": gst["accepted"],
            "band": view["evidence"]["band"], "eligibility": view["eligibility"]["status"],
            "matched": bool(conn.execute(
                "SELECT 1 FROM evidence_item WHERE invoice_id=%s AND signal='irn_valid_matching'",
                (view["id"],)).fetchone()),
            "low_confidence": low_confidence(conn, view["id"]),
            "unpaid": unpaid > 0, "covered": covered, "has_advance": has_advance,
            "past_due": due is not None and as_of > due,
            "supplier_consent": bool(conn.execute(
                "SELECT 1 FROM action_request WHERE invoice_id=%s AND kind='odr_pack' "
                "AND status='approved'", (view["id"],)).fetchone()),
            "approved_action": bool(conn.execute(
                "SELECT 1 FROM action_request WHERE invoice_id=%s AND kind='settlement_offer' "
                "AND status='approved'", (view["id"],)).fetchone())}


def low_confidence(conn, invoice_id) -> bool:
    """An extraction on one of the invoice's documents failed a check or found a mismatch."""
    return bool(conn.execute(
        "SELECT 1 FROM document WHERE invoice_id=%s AND (COALESCE(jsonb_array_length("
        "extracted->'review'),0)>0 OR COALESCE(jsonb_array_length(extracted->'mismatches'),0)>0)",
        (invoice_id,)).fetchone())


def move_state(conn, tenant_id, invoice_id, to: str, as_of: date, actor: str,
               extra: dict | None = None) -> None:
    if to == "needs_review" or (extra or {}).get("manual_review"):
        # these guards read no engine, so they work before the contract and delivery arrive
        facts = {"low_confidence": low_confidence(conn, invoice_id)}
    else:
        facts = guard_facts(conn, tenant_id, invoice_id, as_of)
    states.transition(conn, tenant_id, invoice_id, to, facts | (extra or {}), actor)


def record_advance(conn, tenant_id, invoice_id, principal: str, disbursed_on: date, actor: str):
    """Record a lender disbursement (Hermes moves no money). A verified invoice passes through
    financeable first, under the same guards."""
    amount = Decimal(principal)
    view = invoice_view(conn, tenant_id, invoice_id, disbursed_on)  # NotFound if not ours
    if not Decimal(0) < amount <= Decimal(view["total"]):
        raise ValueError("principal must be positive and at most the invoice total")
    with conn.transaction():
        if view["state"] == "verified":
            move_state(conn, tenant_id, invoice_id, "financeable", disbursed_on, actor)
        conn.execute(
            "INSERT INTO advance (tenant_id, invoice_id, principal, nominal_rate, disbursed_on, "
            "status) SELECT %s,%s,%s,lender_rate_nominal,%s,'open' FROM tenant WHERE id=%s",
            (tenant_id, view["id"], amount, disbursed_on, tenant_id))
        move_state(conn, tenant_id, invoice_id, "advanced", disbursed_on, actor)
    return invoice_view(conn, tenant_id, invoice_id, disbursed_on)


def tick(conn, d: date) -> dict:
    """Daily scheduler job for date d: queue deadline.passed for each unpaid invoice past its
    stored due date (once per invoice per date), and write d's collateral snapshot rows."""
    queued = snapped = 0
    open_invoices = conn.execute(
        "SELECT id::text, tenant_id::text, due_date < %s AND total > COALESCE((SELECT sum(amount) "
        "FROM payment WHERE invoice_id=invoice.id AND paid_on<=%s),0) FROM invoice "
        "WHERE state NOT IN ('paid','closed') ORDER BY id", (d, d)).fetchall()
    for inv, tenant, late in open_invoices:
        if late and not conn.execute(
            "SELECT 1 FROM event_queue WHERE invoice_id=%s AND kind='deadline.passed' "
            "AND payload->>'as_of'=%s", (inv, d.isoformat())).fetchone():
            conn.execute("INSERT INTO event_queue (tenant_id, invoice_id, kind, payload) "
                         "VALUES (%s,%s,'deadline.passed',%s::jsonb)",
                         (tenant, inv, json.dumps({"as_of": d.isoformat()})))
            queued += 1
        v = invoice_view(conn, tenant, inv, d)
        if v["collateral"]:
            conn.execute(
                "INSERT INTO collateral_snapshot (invoice_id, tenant_id, as_of, claim_value, "
                "exposure, ltv, evidence_score, band) VALUES (%s,%s,%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT (invoice_id, as_of) DO UPDATE SET claim_value=EXCLUDED.claim_value, "
                "exposure=EXCLUDED.exposure, ltv=EXCLUDED.ltv, evidence_score=EXCLUDED.evidence_score, "
                "band=EXCLUDED.band",
                (inv, tenant, d, v["claim"]["claim_value"], v["collateral"]["exposure"],
                 v["collateral"]["ltv"], v["evidence"]["score"], v["evidence"]["band"]))
            snapped += 1
            if "ltv_above_band_limit" in v["collateral"]["alerts"] and not conn.execute(
                "SELECT 1 FROM webhook_delivery WHERE event='collateral.ltv_breach' AND "
                "payload->>'invoice_id'=%s AND payload->>'as_of'=%s", (inv, d.isoformat())
            ).fetchone():  # ponytail: while the breach lasts this repeats daily, a standing reminder
                webhooks.publish(conn, tenant, "collateral.ltv_breach",
                                 {"invoice_id": inv, "as_of": d.isoformat()})
    for inv, tenant in conn.execute(
        "UPDATE action_request SET status='expired' WHERE kind='settlement_offer' AND "
        "status='approved' AND (draft->>'expires_on')::date < %s RETURNING invoice_id::text, "
        "tenant_id::text", (d,)).fetchall():
        queue_offer_expired(conn, tenant, inv, d, "expired")
        queued += 1
    return {"date": d.isoformat(), "events_queued": queued, "snapshots": snapped}


def queue_offer_expired(conn, tenant_id, invoice_id, d: date, why: str) -> None:
    conn.execute("INSERT INTO event_queue (tenant_id, invoice_id, kind, payload) "
                 "VALUES (%s,%s,'offer.expired',%s::jsonb)",
                 (tenant_id, invoice_id, json.dumps({"as_of": d.isoformat(), "why": why})))


def _owned(conn, tenant_id, invoice_id) -> str:
    try:
        invoice_id = str(UUID(str(invoice_id)))
    except ValueError:
        raise NotFound("invoice") from None
    if not conn.execute("SELECT 1 FROM invoice WHERE id=%s AND tenant_id=%s",
                        (invoice_id, tenant_id)).fetchone():
        raise NotFound("invoice")
    return invoice_id


def timeline(conn, tenant_id, invoice_id) -> list[dict]:
    """Events, engine runs and state changes for one invoice, oldest first."""
    inv = _owned(conn, tenant_id, invoice_id)
    cur = conn.cursor(row_factory=dict_row)
    rows = (
        [{"kind": "event", "event": r["kind"], "payload": r["payload"], "at": r["at"]}
         for r in cur.execute("SELECT kind, payload, available_at AS at FROM event_queue "
                              "WHERE invoice_id=%s AND tenant_id=%s", (inv, tenant_id))]
        + [{"kind": "engine_run", "engine": r["engine"], "rule_version": r["rule_version"],
            "at": r["at"]}
           for r in cur.execute("SELECT engine, rule_version, run_at AS at FROM engine_run "
                                "WHERE invoice_id=%s AND tenant_id=%s", (inv, tenant_id))]
        + [{"kind": "state_change", "from": r["frm"], "to": r["to"], "actor": r["actor"],
            "at": r["at"]}
           for r in cur.execute("SELECT before->>'state' AS frm, after->>'state' AS to, actor, at "
                                "FROM audit_log WHERE object_id=%s AND tenant_id=%s AND "
                                "action='state_change'", (inv, tenant_id))]
    )
    rows.sort(key=lambda r: r["at"])
    return [{**r, "at": r["at"].isoformat()} for r in rows]


def collateral_series(conn, tenant_id, invoice_id) -> list[dict]:
    """The daily snapshot rows the tick wrote: claim value and exposure over time."""
    inv = _owned(conn, tenant_id, invoice_id)
    return conn.cursor(row_factory=dict_row).execute(
        "SELECT as_of::text, claim_value::text, exposure::text FROM collateral_snapshot "
        "WHERE invoice_id=%s AND tenant_id=%s ORDER BY as_of", (inv, tenant_id)).fetchall()


def _cite(env: dict) -> dict:
    return {"engine": env["engine"], "rule_version": env["rule_version"],
            "input_hash": env["input_hash"]}


def slots(kind: str, lender_consent: bool = False) -> list[tuple]:
    """Who must approve (product spec section 7): one role from each tuple."""
    if kind == "objection":
        return [("hermes_ops",), ("supplier",)]
    if kind == "contract_terms":
        return [("hermes_ops",)]
    if kind == "review":
        return [("lender_approver",)]
    if kind == "doc_link":
        return [("supplier", "hermes_ops")]
    return [("supplier",)] + ([("lender_approver",)] if kind == "settlement_offer" and lender_consent else [])


def outstanding(r: dict) -> list[str]:
    """Approver slots not yet filled, as role names (alternatives joined with /)."""
    left = slots(r["kind"], r["lender_consent_required"])
    for a in r["approvals"]:
        i = next((i for i, s in enumerate(left) if a["role"] in s), None)
        if i is not None:
            del left[i]
    return ["/".join(s) for s in left]


def _action(r: dict) -> dict:
    out = {k: r[k] for k in ("draft", "status", "proposed_by", "reject_reason", "approvals", "kind")}
    out |= {k: None if r[k] is None else str(r[k]) for k in ("id", "invoice_id", "approved_by")}
    out["approved_at"] = r["approved_at"] and r["approved_at"].isoformat()
    out["edit_difference"] = r["edit_difference"]
    out["final_draft"] = (r["draft"] or {}) | {k: v["to"] for k, v in (r["edit_difference"] or {}).items()}
    out["needs"] = outstanding(r) if r["status"] == "proposed" else []
    out["deadline"] = r.get("deadline") and r["deadline"].isoformat()
    out["expires_on"] = (r["draft"] or {}).get("expires_on")
    return out


def propose_action(conn, tenant_id, invoice_id, kind: str, draft: dict, actor: str,
                   deadline: date | None = None) -> dict:
    """The agent's draft of any other gated action; nothing happens until people approve."""
    if kind == "settlement_offer" or kind not in ("buyer_note", "gstr1a_draft",
                                                  "doc_link", "objection", "contract_terms", "review"):
        raise ValueError(f"unsupported action kind {kind}")
    if not isinstance(draft, dict):
        raise TypeError("draft must be an object")
    inv = _owned(conn, tenant_id, invoice_id)
    row = conn.cursor(row_factory=dict_row).execute(
        "INSERT INTO action_request (tenant_id, invoice_id, kind, draft, status, proposed_by, "
        "expires_at) VALUES (%s,%s,%s,%s::jsonb,'proposed',%s,%s) RETURNING *, "
        "expires_at::date AS deadline", (tenant_id, inv, kind, json.dumps(draft), actor, deadline)).fetchone()
    return _action(row)


def _settlement_run(conn, tenant_id, inv_id, as_of: date, discount: str = "0"):
    """Run the engines for the invoice as of a date and the settlement engine over them (which
    also holds the dispute pack). Returns the settlement envelope and the other envelopes."""
    cur = conn.cursor(row_factory=dict_row)
    env: dict = {}
    view = invoice_view(conn, tenant_id, inv_id, as_of, env)
    if view["claim"] is None or "interest" not in env:
        raise states.Refused("no statutory claim to offer on yet")
    row = cur.execute(
        "SELECT i.invoice_no, i.invoice_date::text, s.legal_name AS supplier, b.legal_name AS buyer "
        "FROM invoice i JOIN supplier s ON s.id=i.supplier_id JOIN buyer b ON b.id=i.buyer_id "
        "WHERE i.id=%s", (inv_id,)).fetchone()
    docs = cur.execute("SELECT id::text, doc_type AS title, COALESCE(gcs_uri, 'ledger') AS source "
                       "FROM document WHERE invoice_id=%s AND tenant_id=%s ORDER BY id",
                       (inv_id, tenant_id)).fetchall()
    out = run_engine(conn, tenant_id, inv_id, "settlement", {
        "invoice": {"invoice_no": row["invoice_no"], "invoice_date": row["invoice_date"],
                    "principal": view["claim"]["principal"], "supplier_name": row["supplier"],
                    "buyer_name": row["buyer"]},
        "as_of": as_of.isoformat(), "discount_percent": discount, "agreed_costs": "0",
        "documents": docs,
        "eligibility": env["eligibility"], "deadline": env["deadline"], "interest": env["interest"],
        "collateral": env["collateral"], "evidence": env["evidence"]}, reuse=True)
    return out, env


def propose_settlement_offer(conn, tenant_id, invoice_id, as_of: date, actor: str,
                             model=None) -> dict:
    """The agent's draft: the settlement engine's letter, filled from the other engines' output,
    with the engine runs it relies on. One live offer per invoice; asking again returns it.
    The letter prose is the model's when its draft passes the checks, else the plain template.
    Nothing is sent: a person approves first."""
    inv_id = _owned(conn, tenant_id, invoice_id)
    cur = conn.cursor(row_factory=dict_row)
    live = cur.execute(
        "SELECT * FROM action_request WHERE invoice_id=%s AND kind='settlement_offer' AND "
        "status IN ('proposed','approved','sent')", (inv_id,)).fetchone()
    if live:
        return _action(live)
    out, env = _settlement_run(conn, tenant_id, inv_id, as_of)
    r = out["result"]
    draft = _offer_draft(r, as_of, out, env, model)
    new = cur.execute(
        "INSERT INTO action_request (tenant_id, invoice_id, kind, draft, status, proposed_by, "
        "lender_consent_required) VALUES (%s,%s,'settlement_offer',%s::jsonb,'proposed',%s,%s) "
        "RETURNING *", (tenant_id, inv_id, json.dumps(draft), actor,
                        r["needs_lender_consent"])).fetchone()
    if r["needs_lender_consent"]:
        webhooks.publish(conn, tenant_id, "action.awaiting_lender",
                         {"invoice_id": str(inv_id), "action_id": str(new["id"])})
    return _action(new)


def _offer_draft(r: dict, as_of: date, out: dict, env: dict, model) -> dict:
    text, source = letter.draft_letter(model, r)
    return {"offer": r["offer_display"], "floor": r["floor_display"], "as_of": r["as_of"],
            "expires_on": (as_of + timedelta(days=OFFER_DAYS)).isoformat(),
            "needs_lender_consent": r["needs_lender_consent"], "letter": text,
            "letter_source": source, "discount_percent": r["discount_percent"],
            "cites": [_cite(e) for e in (env["eligibility"], env["deadline"], env["interest"],
                                         env["collateral"], env["evidence"], out)]}


def set_discount(conn, tenant_id, action_id, user_id: str, role: str, percent, model=None,
                 supplier_id: str | None = None) -> dict:
    """The supplier's discount on statutory interest. The settlement engine recomputes the offer,
    the floor check and the letter; earlier approvals were for different figures, so they clear.
    A below-floor result now needs the lender's consent, and one at or above no longer does."""
    try:
        percent = str(Decimal(str(percent)))
    except ArithmeticError:
        raise ValueError("discount_percent must be a number") from None
    with conn.transaction():
        row = _lock_action(conn, tenant_id, action_id, role, supplier_id)
        if row["kind"] != "settlement_offer":
            raise ValueError("only a settlement offer takes a discount")
        as_of = date.fromisoformat(row["draft"]["as_of"])
        out, env = _settlement_run(conn, tenant_id, row["invoice_id"], as_of, percent)
        r = out["result"]
        draft = _offer_draft(r, as_of, out, env, model) | {"expires_on": row["draft"]["expires_on"]}
        conn.execute("UPDATE action_request SET draft=%s::jsonb, approvals='[]'::jsonb, "
                     "edit_difference=NULL, lender_consent_required=%s WHERE id=%s",
                     (json.dumps(draft), r["needs_lender_consent"], row["id"]))
        if r["needs_lender_consent"] and not row["lender_consent_required"]:
            webhooks.publish(conn, tenant_id, "action.awaiting_lender",
                             {"invoice_id": str(row["invoice_id"]), "action_id": str(row["id"])})
        _audit_action(conn, tenant_id, role, user_id, "discount", row, discount_percent=percent)
        return _fresh(conn, row["id"])


def propose_dispute_pack(conn, tenant_id, invoice_id, as_of: date, actor: str) -> dict:
    """The agent draft of a dispute pack for the supplier to release, with the settlement
    engine pack (the PDF is rendered from it on download). One live pack per invoice. The
    invoice must be at settlement_offered: the offer has expired or been refused. Hermes only
    drafts; a person files on the portal."""
    inv_id = _owned(conn, tenant_id, invoice_id)
    cur = conn.cursor(row_factory=dict_row)
    live = cur.execute("SELECT * FROM action_request WHERE invoice_id=%s AND kind='odr_pack' AND "
                       "status IN ('proposed','approved')", (inv_id,)).fetchone()
    if live:
        return _action(live)
    if cur.execute("SELECT state FROM invoice WHERE id=%s", (inv_id,)).fetchone()["state"] \
            != "settlement_offered":
        raise states.Refused("a dispute pack follows an offer that expired or was refused")
    out, env = _settlement_run(conn, tenant_id, inv_id, as_of)
    draft = {"as_of": as_of.isoformat(), "pack": out["result"]["dispute_pack"],
             "cites": [_cite(e) for e in (env["eligibility"], env["deadline"], env["interest"],
                                          env["collateral"], env["evidence"], out)]}
    return _action(cur.execute(
        "INSERT INTO action_request (tenant_id, invoice_id, kind, draft, status, proposed_by) "
        "VALUES (%s,%s,'odr_pack',%s::jsonb,'proposed',%s) RETURNING *",
        (tenant_id, inv_id, json.dumps(draft), actor)).fetchone())


def dispute_pack(conn, tenant_id, action_id) -> tuple[dict, dict]:
    """The stored pack of a dispute-pack action: (pack JSON, render input for the PDF)."""
    try:
        action_id = str(UUID(str(action_id)))
    except ValueError:
        raise NotFound("action") from None
    row = conn.execute("SELECT draft FROM action_request WHERE id=%s AND tenant_id=%s AND "
                       "kind='odr_pack'", (action_id, tenant_id)).fetchone()
    if row is None:
        raise NotFound("action")
    return row[0]["pack"], {"as_of": row[0]["as_of"], "dispute_pack": row[0]["pack"]}


def list_actions(conn, tenant_id, status: str | None, role: str | None = None,
                 supplier_id: str | None = None) -> list[dict]:
    """One queue across kinds, soonest deadline first (the action's own, else the invoice's due
    date). With a role, only the items that role may act on (a supplier: its own invoices)."""
    rows = conn.cursor(row_factory=dict_row).execute(
        "SELECT a.*, COALESCE(a.expires_at::date, i.due_date) AS deadline, i.supplier_id::text AS sup "
        "FROM action_request a JOIN invoice i ON i.id=a.invoice_id "
        "WHERE a.tenant_id=%s AND (%s::text IS NULL OR a.status=%s) "
        "ORDER BY COALESCE(a.expires_at::date, i.due_date) NULLS LAST, a.id",
        (tenant_id, status, status)).fetchall()
    out = []
    for r in rows:
        if role and (not any(role in s for s in slots(r["kind"], r["lender_consent_required"]))
                     or (role == "supplier" and r["sup"] != supplier_id)):
            continue
        a = _action(r)
        ids = (r["draft"] or {}).get("document_ids") or [x[0] for x in conn.execute(
            "SELECT DISTINCT source_ref->>'document_id' FROM evidence_item WHERE invoice_id=%s "
            "AND source_ref ? 'document_id'", (r["invoice_id"],))]
        a["sources"] = [x for x in (run_ref(conn, tenant_id, r["invoice_id"], c["engine"], c["input_hash"])
                                    for c in (r["draft"] or {}).get("cites") or []) if x]
        a["documents"] = [{"id": x[0], "doc_type": x[1]} for x in conn.execute(
            "SELECT id::text, doc_type FROM document WHERE tenant_id=%s AND id::text = ANY(%s)",
            (tenant_id, ids))]
        out.append(a)
    return out


NOT_EDITABLE = {"offer", "floor", "as_of", "expires_on", "needs_lender_consent", "cites", "pack",
                "letter_source", "discount_percent"}


def _lock_action(conn, tenant_id, action_id, role: str, supplier_id: str | None) -> dict:
    """The proposed action, row-locked, for a person whose role holds one of its approver slots."""
    try:
        action_id = str(UUID(str(action_id)))
    except ValueError:
        raise NotFound("action") from None
    row = conn.cursor(row_factory=dict_row).execute(
        "SELECT a.*, i.supplier_id::text AS sup FROM action_request a JOIN invoice i ON i.id=a.invoice_id "
        "WHERE a.id=%s AND a.tenant_id=%s FOR UPDATE OF a", (action_id, tenant_id)).fetchone()
    if row is None or (role == "supplier" and row["sup"] != supplier_id):
        raise NotFound("action")
    if row["status"] != "proposed":
        raise states.Refused(f"action is already {row['status']}")
    if not any(role in sl for sl in slots(row["kind"], row["lender_consent_required"])):
        raise PermissionError(f"{role} cannot decide a {row['kind']}")
    return row


def _audit_action(conn, tenant_id, role, user_id, verb, row, **after):
    conn.execute(
        "INSERT INTO audit_log (tenant_id, actor, action, object_type, object_id, after) "
        "VALUES (%s,%s,%s,'action_request',%s,%s::jsonb)",
        (tenant_id, f"{role}:{user_id}", verb, row["id"],
         json.dumps({"kind": row["kind"], "edit_difference": row["edit_difference"]} | after)))


def _fresh(conn, action_id) -> dict:
    return _action(conn.cursor(row_factory=dict_row).execute(
        "SELECT * FROM action_request WHERE id=%s", (action_id,)).fetchone())


def decide_action(conn, tenant_id, action_id, user_id: str, role: str, approve: bool,
                  reason: str | None = None, supplier_id: str | None = None):
    """A named person approves or rejects a proposed action. Each approver slot (see slots) is
    filled by one person; the action is approved once all are, and only then does anything move:
    a settlement offer takes the invoice to settlement_offered, a dispute pack (the supplier's
    consent to escalate) to odr_ready, and an action.approved event is queued. Any slot holder
    may reject, with a reason."""
    if not approve and not (reason or "").strip():
        raise ValueError("a rejection needs a reason")
    with conn.transaction():
        row = _lock_action(conn, tenant_id, action_id, role, supplier_id)
        if not approve:
            conn.execute("UPDATE action_request SET status='rejected', approved_by=%s, "
                         "approved_at=now(), reject_reason=%s WHERE id=%s", (user_id, reason, row["id"]))
            _audit_action(conn, tenant_id, role, user_id, "reject", row, reason=reason)
            return _fresh(conn, row["id"])
        if any(a["user"] == str(user_id) for a in row["approvals"]) or role not in "/".join(
                outstanding(row)).split("/"):
            raise states.Refused("this approver slot is already filled")
        email = conn.execute("SELECT email FROM app_user WHERE id=%s", (user_id,)).fetchone()[0]
        row["approvals"] = row["approvals"] + [
            {"user": str(user_id), "email": email, "role": role,
             "at": datetime.now(UTC).isoformat()}]
        done = not outstanding(row)
        conn.execute(
            "UPDATE action_request SET approvals=%s::jsonb, status=%s, approved_by=%s, approved_at=%s, "
            "lender_consent_by=CASE WHEN %s THEN %s ELSE lender_consent_by END, "
            "lender_consent_at=CASE WHEN %s THEN now() ELSE lender_consent_at END WHERE id=%s",
            (json.dumps(row["approvals"]), "approved" if done else "proposed",
             user_id if done else None, datetime.now(UTC) if done else None,
             role == "lender_approver", user_id, role == "lender_approver", row["id"]))
        _audit_action(conn, tenant_id, role, user_id, "approve", row, reason=None, final=done)
        if done:
            as_of = (row["draft"] or {}).get("as_of")
            target = {"settlement_offer": "settlement_offered", "odr_pack": "odr_ready"}.get(row["kind"])
            if row["kind"] == "objection":  # a confirmed objection on a funded invoice
                raise_hard_flag(conn, tenant_id, row["invoice_id"], "written_objection",
                                {"action_id": str(row["id"])})
            if target:
                move_state(conn, tenant_id, row["invoice_id"], target, date.fromisoformat(as_of),
                           f"user:{user_id}")
            conn.execute("INSERT INTO event_queue (tenant_id, invoice_id, kind, payload) "
                         "VALUES (%s,%s,'action.approved',%s::jsonb)",
                         (tenant_id, row["invoice_id"], json.dumps({"action_id": str(row["id"]),
                                                                    "kind": row["kind"]})))
        return _fresh(conn, row["id"])


def edit_action(conn, tenant_id, action_id, user_id: str, role: str, changes: dict,
                supplier_id: str | None = None):
    """An approver edits the draft's wording. The draft stays as the agent wrote it; the edit is
    stored as a difference against it, and earlier approvals are cleared since they were given
    to a different text. Figures from the engines are not editable."""
    if not isinstance(changes, dict) or not changes:
        raise ValueError("changes must be a non-empty object")
    with conn.transaction():
        row = _lock_action(conn, tenant_id, action_id, role, supplier_id)
        draft, diff = row["draft"] or {}, dict(row["edit_difference"] or {})
        for k, v in changes.items():
            if k not in draft or k in NOT_EDITABLE or not isinstance(v, str):
                raise ValueError(f"{k} cannot be edited")
            if v == draft[k]:
                diff.pop(k, None)
            else:
                diff[k] = {"from": draft[k], "to": v}
        conn.execute("UPDATE action_request SET edit_difference=%s::jsonb, approvals='[]'::jsonb "
                     "WHERE id=%s", (json.dumps(diff or None), row["id"]))
        row["edit_difference"] = diff or None
        _audit_action(conn, tenant_id, role, user_id, "edit", row)
        return _fresh(conn, row["id"])


def record_payment(conn, tenant_id, invoice_id, amount: str, paid_on: date, utr, actor: str) -> dict:
    """Development payment entry: a receipt, and a payment.received event for the agent."""
    inv = _owned(conn, tenant_id, invoice_id)
    if not Decimal(0) < Decimal(amount):
        raise ValueError("amount must be positive")
    with conn.transaction():
        conn.execute("INSERT INTO payment (tenant_id, invoice_id, amount, paid_on, utr, source) "
                     "VALUES (%s,%s,%s,%s,%s,'development entry')",
                     (tenant_id, inv, Decimal(amount), paid_on, utr))
        conn.execute("INSERT INTO event_queue (tenant_id, invoice_id, kind, payload) "
                     "VALUES (%s,%s,'payment.received',%s::jsonb)",
                     (tenant_id, inv, json.dumps({"as_of": paid_on.isoformat(), "amount": amount})))
        conn.execute("INSERT INTO audit_log (tenant_id, actor, action, object_type, object_id, after) "
                     "VALUES (%s,%s,'payment','invoice',%s,%s::jsonb)",
                     (tenant_id, actor, inv, json.dumps({"amount": amount, "utr": utr})))
    return {"invoice_id": inv, "amount": amount, "paid_on": paid_on.isoformat()}


def run_waterfall(conn, tenant_id, invoice_id, as_of: date) -> dict:
    """Split the receipts: the lender's exposure and agreed costs first, the rest (all statutory
    interest) to the supplier. The collateral engine does the arithmetic; this stores its answer."""
    env: dict = {}
    view = invoice_view(conn, tenant_id, invoice_id, as_of, env)
    if view["state"] != "paid":
        raise states.Refused("waterfall runs once the invoice is paid")
    receipts = conn.execute("SELECT COALESCE(sum(amount),0) FROM payment WHERE invoice_id=%s "
                            "AND paid_on<=%s", (view["id"], as_of)).fetchone()[0]
    out = run_engine(conn, tenant_id, view["id"], "collateral",
                     env["collateral_inputs"] | {"receipts": str(receipts), "agreed_costs": "0"})
    w = out["result"]["waterfall"]
    conn.execute(
        "INSERT INTO waterfall (invoice_id, tenant_id, as_of, receipts, lender_exposure, costs, "
        "supplier, rule_version, input_hash) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) "
        "ON CONFLICT (invoice_id) DO UPDATE SET as_of=EXCLUDED.as_of, receipts=EXCLUDED.receipts, "
        "lender_exposure=EXCLUDED.lender_exposure, costs=EXCLUDED.costs, supplier=EXCLUDED.supplier, "
        "rule_version=EXCLUDED.rule_version, input_hash=EXCLUDED.input_hash",
        (view["id"], tenant_id, as_of, receipts, w["lender_exposure"], w["costs"], w["supplier"],
         out["rule_version"], out["input_hash"]))
    return _waterfall_row(conn.cursor(row_factory=dict_row), tenant_id, view["id"])


def confirm_repayment(conn, tenant_id, invoice_id, actor: str) -> None:
    """The lender confirms the advance is repaid: marks it repaid and closes the invoice."""
    inv = _owned(conn, tenant_id, invoice_id)
    w = conn.execute("SELECT as_of FROM waterfall WHERE invoice_id=%s", (inv,)).fetchone()
    if w is None:
        raise states.Refused("waterfall has not run")
    with conn.transaction():
        move_state(conn, tenant_id, inv, "closed", w[0], actor, {"lender_confirmed": True})
        conn.execute("UPDATE advance SET status='repaid', repaid_on=%s WHERE invoice_id=%s",
                     (w[0], inv))


def refuse_offer(conn, tenant_id, invoice_id, actor: str, as_of: date) -> None:
    """Lender ops records that the buyer refused the approved offer: it ends like an expiry."""
    inv = _owned(conn, tenant_id, invoice_id)
    with conn.transaction():
        n = conn.execute(
            "UPDATE action_request SET status='expired', reject_reason='refused by the buyer' "
            "WHERE invoice_id=%s AND kind='settlement_offer' AND status='approved'", (inv,)).rowcount
        if not n:
            raise states.Refused("no approved offer to refuse")
        queue_offer_expired(conn, tenant_id, inv, as_of, "refused")
        conn.execute("INSERT INTO audit_log (tenant_id, actor, action, object_type, object_id) "
                     "VALUES (%s,%s,'offer_refused','invoice',%s)", (tenant_id, actor, inv))


def record_case_number(conn, tenant_id, invoice_id, case_number: str, as_of: date, actor: str):
    """A person filed the pack on the portal and entered the case number: the invoice is filed.
    Hermes submits nothing; this is the only way the invoice reaches odr_filed."""
    inv = _owned(conn, tenant_id, invoice_id)
    case_number = (case_number or "").strip()
    if not case_number:
        raise ValueError("case number is required")
    with conn.transaction():
        move_state(conn, tenant_id, inv, "odr_filed", as_of, actor, {"case_number": case_number})
        conn.execute("UPDATE invoice SET case_number=%s WHERE id=%s", (case_number, inv))


def record_award(conn, tenant_id, invoice_id, filename: str, content_b64: str, as_of: date,
                 actor: str) -> None:
    """Record the award: the uploaded award document is stored (hash and name; the prototype keeps
    no file store) and the invoice moves to awarded. No document, no award."""
    inv = _owned(conn, tenant_id, invoice_id)
    try:
        content = base64.b64decode(content_b64 or "", validate=True)
    except (binascii.Error, TypeError):
        raise ValueError("award document is not valid base64") from None
    if not filename or not content:
        raise ValueError("an award document (filename and content) is required")
    sha = hashlib.sha256(content).hexdigest()
    with conn.transaction():
        conn.execute("INSERT INTO document (tenant_id, invoice_id, doc_type, gcs_uri, sha256) "
                     "VALUES (%s,%s,'award',%s,%s)", (tenant_id, inv, f"upload://{filename}", sha))
        move_state(conn, tenant_id, inv, "awarded", as_of, actor, {"award_document": True})


# IMS rejection reason codes the supplier can fix by amending their own filing (the buyer's
# disputes carry none). ponytail: a fixed list; the live IMS feed's real codes replace it.
FIXABLE = ("invoice_details_mismatch", "wrong_pos", "wrong_value", "wrong_table")
RULE = ("CGST Act 2017 s.37 and CGST Rules 2017 Rule 59: a supply to a registered buyer is reported "
        "in the B2B table with the buyer's GSTIN; a wrong entry is amended through GSTR-1A or a "
        "GSTR-1 amendment.")
NOTE = ("Prepared for the supplier and their accountant. Hermes files nothing; the supplier or their "
        "accountant files on the GST portal. This is not legal advice or tax advice: please check "
        "the steps with a chartered accountant.")


def gst_facts(conn, tenant_id, invoice_id) -> dict:
    """What the supplier's GSTR-1 and the buyer's IMS view say about an invoice: `blocked` when
    it was filed under B2C large (so the buyer never sees it) or the buyer's IMS rejected it for
    a reason the supplier can fix, `accepted` when the latest IMS action is accepted."""
    inv = conn.execute("SELECT invoice_no, supplier_id FROM invoice WHERE id=%s AND tenant_id=%s",
                       (invoice_id, tenant_id)).fetchone()
    last = conn.execute(
        "SELECT e.action, r.payload FROM ims_event e LEFT JOIN raw_record r ON r.id::text=e.raw_ref "
        "WHERE e.invoice_id=%s ORDER BY e.id DESC LIMIT 1", (invoice_id,)).fetchone()
    filed = conn.execute(
        "SELECT payload FROM raw_record WHERE tenant_id=%s AND supplier_id=%s AND source='gstr1' "
        "AND payload->>'inum'=%s ORDER BY fetched_at DESC LIMIT 1",
        (tenant_id, inv[1], inv[0])).fetchone()
    wrong_table = filed is not None and filed[0]["table"] == "b2cl" and last is None
    code = (last[1] or {}).get("reason_code") if last and last[0] == "rejected" else None
    return {"blocked": wrong_table or code in FIXABLE,
            "accepted": last is not None and last[0] == "accepted",
            "wrong_table": wrong_table, "reason_code": code}


def propose_gstr1a_draft(conn, tenant_id, invoice_id, as_of: date, actor: str) -> dict:
    """The agent's code-generated correction draft for a GST-blocked invoice: what was filed, what
    should have been, the steps to amend. For the supplier and their accountant to approve or
    dismiss; Hermes files nothing. One live draft per invoice."""
    inv_id = _owned(conn, tenant_id, invoice_id)
    cur = conn.cursor(row_factory=dict_row)
    live = cur.execute("SELECT * FROM action_request WHERE invoice_id=%s AND kind='gstr1a_draft' AND "
                       "status IN ('proposed','approved')", (inv_id,)).fetchone()
    if live:
        return _action(live)
    g = gst_facts(conn, tenant_id, inv_id)
    if not g["blocked"]:
        raise states.Refused("nothing to correct: the buyer's IMS view has this invoice")
    i = cur.execute("SELECT i.invoice_no, i.invoice_date::text AS d, i.total::text AS total, "
                    "b.gstin FROM invoice i JOIN buyer b ON b.id=i.buyer_id WHERE i.id=%s",
                    (inv_id,)).fetchone()
    should = {"table": "B2B", "buyer_gstin": i["gstin"]}
    if g["wrong_table"]:
        filed = {"table": "B2CL", "buyer_gstin": None, "source": "gstr1",
                 "what": "filed as a B2C large invoice with no buyer GSTIN, so it never reached "
                         "the buyer's IMS"}
        steps = [f"Find invoice {i['invoice_no']} ({i['d']}, Rs {i['total']}) in the GSTR-1 B2CL table.",
                 ("Amend it into the B2B table with the buyer's GSTIN above, through GSTR-1A or the "
                  "GSTR-1 amendment tables for the period."),
                 "File the amendment on the GST portal (the supplier or their accountant does this).",
                 "Once the buyer's IMS shows the invoice as accepted, Hermes moves it back to verified."]
    else:
        filed = {"table": "B2B", "buyer_gstin": i["gstin"], "source": "ims", "ims_action": "rejected",
                 "what": f"rejected in the buyer's IMS (reason: {g['reason_code']})"}
        steps = [f"Check invoice {i['invoice_no']} against the IMS rejection reason: {g['reason_code']}.",
                 ("Amend the invoice details in GSTR-1A or the GSTR-1 amendment tables to match "
                  "your invoice."),
                 "File the amendment on the GST portal (the supplier or their accountant does this).",
                 ("Ask the buyer to accept the corrected record in IMS; Hermes then moves the "
                  "invoice back to verified.")]
    draft = {"as_of": as_of.isoformat(), "audience": "supplier_and_accountant", "filed": filed,
             "should_have_been": should, "steps": steps, "rule": RULE, "note": NOTE}
    return _action(cur.execute(
        "INSERT INTO action_request (tenant_id, invoice_id, kind, draft, status, proposed_by) "
        "VALUES (%s,%s,'gstr1a_draft',%s::jsonb,'proposed',%s) RETURNING *",
        (tenant_id, inv_id, json.dumps(draft), actor)).fetchone())
