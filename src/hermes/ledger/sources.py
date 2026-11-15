"""Every figure opens its source (ticket 27). A source reference (see service.run_ref and
service._evidence_ref) is {kind, id, ...}; `resolve` returns the record it names, scoped to the
caller's tenant (a supplier: its own records), and `recompute` re-runs a stored engine run."""

import json

import psycopg
from psycopg.rows import dict_row

from hermes.ledger.service import ENGINES, NotFound

# kind -> (query returning the record plus `sup`, the owning supplier, for scoping)
QUERIES = {
    "engine_run": "SELECT r.id::text, r.invoice_id::text, r.engine, r.rule_version, r.inputs_hash AS input_hash, "
                  "r.inputs, r.outputs->'result' AS result, r.outputs->'reasons' AS reasons, "
                  "r.run_at::text, i.supplier_id::text AS sup FROM engine_run r "
                  "LEFT JOIN invoice i ON i.id=r.invoice_id WHERE r.id=%s AND r.tenant_id=%s",
    "document": "SELECT d.id::text, d.invoice_id::text, d.doc_type, d.filename, d.extracted, "
                "d.extraction_model, d.content IS NOT NULL AS has_content, "
                "COALESCE(d.supplier_id, i.supplier_id)::text AS sup FROM document d "
                "LEFT JOIN invoice i ON i.id=d.invoice_id WHERE d.id=%s AND d.tenant_id=%s",
    "ims_event": "SELECT e.id::text, e.invoice_id::text, e.action, e.action_at::text, e.raw_ref, "
                 "e.fetched_at::text, i.supplier_id::text AS sup FROM ims_event e "
                 "JOIN invoice i ON i.id=e.invoice_id WHERE e.id::text=%s AND e.tenant_id=%s",
    "payment": "SELECT p.id::text, p.invoice_id::text, p.amount::text, p.paid_on::text, p.utr, p.source, "
               "i.supplier_id::text AS sup FROM payment p JOIN invoice i ON i.id=p.invoice_id "
               "WHERE p.id=%s AND p.tenant_id=%s",
    "raw_record": "SELECT id::text, source, sha256, external_id, fetched_at::text, "
                  "supplier_id::text AS sup FROM raw_record WHERE id=%s AND tenant_id=%s",
    "evidence_item": "SELECT e.id::text, e.invoice_id::text, e.signal, e.value, e.source_ref, "
                     "e.detected_at::text, i.supplier_id::text AS sup FROM evidence_item e "
                     "JOIN invoice i ON i.id=e.invoice_id WHERE e.id=%s AND e.tenant_id=%s",
    "invoice": "SELECT id::text, id::text AS invoice_id, invoice_no, invoice_date::text, total::text, "
               "taxable_value::text, gst_amount::text, irn, ewb_no, supplier_id::text AS sup "
               "FROM invoice WHERE id=%s AND tenant_id=%s",
    "contract": "SELECT id::text, signed_date::text, written_payment_days, terms_source, "
                "supplier_id::text AS sup FROM contract WHERE id=%s AND tenant_id=%s",
}


def resolve(conn, tenant_id, kind: str, ref_id: str, supplier_id: str | None = None) -> dict:
    """The record a source reference names. Anything not found, or not the supplier's, is NotFound."""
    if kind not in QUERIES:
        raise NotFound("source")
    try:
        row = conn.cursor(row_factory=dict_row).execute(QUERIES[kind], (ref_id, tenant_id)).fetchone()
    except psycopg.Error:  # a malformed id
        raise NotFound("source") from None
    if row is None or (supplier_id is not None and row.pop("sup") != supplier_id):
        raise NotFound("source")
    row.pop("sup", None)
    out = {"kind": kind, **row}
    if kind == "engine_run":
        out["provisional"] = any("Awaiting legal review" in r for r in row["reasons"] or [])
    if kind == "document":
        ex = row.pop("extracted") or {}
        out.pop("extracted")
        out["content_url"] = f"/v1/documents/{ref_id}/content" if row["has_content"] else None
        out["fields"] = [{"field": f, "value": ex.get(f), "page": s.get("page"), "quote": s.get("quote")}
                         for f, s in (ex.get("sources") or {}).items()]
    return out


def recompute(conn, tenant_id, run_id: str, supplier_id: str | None = None) -> dict:
    """Run a stored engine run again from its stored inputs; report whether the output matches.
    Nothing is stored. A changed rule version is reported as such: the output then differs."""
    run = resolve(conn, tenant_id, "engine_run", run_id, supplier_id)
    stored = conn.execute("SELECT outputs FROM engine_run WHERE id=%s", (run_id,)).fetchone()[0]
    new = json.loads(json.dumps(ENGINES[run["engine"]](run["inputs"])))
    diff = sorted(k for k in {*stored, *new} if stored.get(k) != new.get(k))
    return {"id": run_id, "engine": run["engine"], "matches": not diff, "differs_in": diff,
            "stored_rule_version": stored["rule_version"], "current_rule_version": new["rule_version"],
            "stored_input_hash": stored["input_hash"], "recomputed_input_hash": new["input_hash"]}
