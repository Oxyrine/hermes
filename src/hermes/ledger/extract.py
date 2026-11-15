"""Store what the scripted runner read from a document (ticket 18). The runner is not trusted: the
checks run again here on the stored bytes, fields that fail are not kept, and a disagreement with
the GSTR-1 or e-invoice record, or among purchase order, goods receipt and invoice, is stored as
mismatch evidence on the document. The state machine then reads `low_confidence` from it."""

import json

from psycopg.rows import dict_row

from hermes import adapters
from hermes.checks import check_cross_source
from hermes.extraction import DB_TYPE, FIELDS, check_fields, pdf_text, three_way
from hermes.ledger import ingest, service

KIND = {v: k for k, v in DB_TYPE.items()}  # db type -> document type name


def _records(conn, tenant_id, inv_no, supplier_id) -> dict:
    """The invoice as the GSTR-1 and e-invoice records state it, in the extraction's terms."""
    out = {}
    row = conn.execute(
        "SELECT payload FROM raw_record WHERE tenant_id=%s AND supplier_id=%s AND source='gstr1' "
        "AND payload->>'inum'=%s ORDER BY fetched_at DESC LIMIT 1",
        (tenant_id, supplier_id, inv_no)).fetchone()
    if row:
        p = row[0]
        out["gstr1"] = {"invoice_no": p["inum"], "invoice_date": ingest._d(p["idt"]), "total": p["val"]}
    for (p,) in conn.execute("SELECT payload FROM raw_record WHERE tenant_id=%s AND supplier_id=%s "
                             "AND source='einvoice'", (tenant_id, supplier_id)).fetchall():
        c = adapters.qr_claims(p["qr"])[0]
        if c["DocNo"] == inv_no:
            out["einvoice"] = {"invoice_no": c["DocNo"], "invoice_date": ingest._d(c["DocDt"]),
                               "total": c["TotInvVal"], "irn": c["Irn"]}
    return out


def _cross_source(conn, tenant_id, doc, clean) -> list[dict]:
    inv = conn.cursor(row_factory=dict_row).execute(
        "SELECT i.invoice_no, i.supplier_id::text, b.gstin FROM invoice i "
        "JOIN buyer b ON b.id=i.buyer_id WHERE i.id=%s", (doc["invoice_id"],)).fetchone()
    out = []
    if clean.get("buyer_gstin") not in (None, inv["gstin"]):
        out.append({"field": "buyer GSTIN", "between": ["invoice", "ledger"],
                    "values": {"extracted": clean["buyer_gstin"], "ledger": inv["gstin"]}})
    for src, rec in _records(conn, tenant_id, inv["invoice_no"], inv["supplier_id"]).items():
        out += [{"field": m["field"], "between": ["invoice", src],
                 "values": {"extracted": m["extracted"], src: m["record"]}}
                for m in check_cross_source(clean, rec)]
    return out


def store_extraction(conn, tenant_id, document_id: str, payload: dict, actor: str) -> dict:
    """-> {"review": [problems], "mismatches": [...]}; the document row keeps the usable fields,
    the model, the confidence and both lists."""
    cur = conn.cursor(row_factory=dict_row)
    doc = cur.execute("SELECT id::text, invoice_id::text, supplier_id::text, doc_type, content "
                      "FROM document WHERE id=%s AND tenant_id=%s AND content IS NOT NULL",
                      (document_id, tenant_id)).fetchone()
    if doc is None or doc["doc_type"] not in KIND or doc["invoice_id"] is None:
        raise service.NotFound("document")
    cls, ext = payload.get("classification"), payload.get("extraction")
    problems = [payload["reason"]] if payload.get("reason") else []
    kind = (cls or {}).get("doc_type") or KIND[doc["doc_type"]]
    if cls and DB_TYPE.get(kind) != doc["doc_type"]:
        problems.append(f"classified as {kind}, filed as {KIND[doc['doc_type']]}")
    clean = {}
    if ext and kind in FIELDS:
        clean, more = check_fields(kind, ext["data"], pdf_text(bytes(doc["content"])))
        problems += more
    elif not problems:
        problems.append("nothing was extracted")
    if doc["doc_type"] in ("grn", "challan") and f"{doc['doc_type']}_date" in clean:
        clean["delivery_date"] = clean[f"{doc['doc_type']}_date"]
    mismatches = []
    if clean and doc["doc_type"] == "invoice":
        mismatches += _cross_source(conn, tenant_id, doc, clean)
    siblings = {r["doc_type"]: r["extracted"] for r in cur.execute(
        "SELECT doc_type, extracted FROM document WHERE invoice_id=%s AND id<>%s AND extracted "
        "IS NOT NULL AND doc_type IN ('invoice','po','grn') ORDER BY id",
        (doc["invoice_id"], document_id)).fetchall()}
    trio = siblings | ({doc["doc_type"]: clean}
                       if clean and doc["doc_type"] in ("invoice", "po", "grn") else {})
    mismatches += [m for m in three_way(trio) if doc["doc_type"] in m["between"]]
    conn.execute(
        "UPDATE document SET extracted=%s::jsonb, extraction_model=%s, extraction_confidence=%s "
        "WHERE id=%s", (json.dumps({**clean, "review": problems, "mismatches": mismatches}),
                        ext and ext.get("model"), ext and ext.get("confidence"), document_id))
    t, inv = tenant_id, doc["invoice_id"]
    if not problems and not mismatches:
        def once(signal, ref):
            if not conn.execute("SELECT 1 FROM evidence_item WHERE invoice_id=%s AND signal=%s",
                                (inv, signal)).fetchone():
                ingest._evidence(conn, t, inv, signal, ref)
        if doc["doc_type"] == "invoice":
            e = _records(conn, t, clean["invoice_no"], doc["supplier_id"]).get("einvoice")
            if e and e["irn"] == clean.get("irn"):
                once("irn_valid_matching", {"document_id": document_id, "irn": e["irn"]})
        elif doc["doc_type"] in ("po", "grn") and "invoice" in trio:
            once(f"{doc['doc_type']}_matching",
                 {"document_id": document_id, "doc_type": doc["doc_type"]})
        if doc["doc_type"] == "po":
            ingest._contract(conn, t, inv, clean["po_date"])
        if doc["doc_type"] in ("grn", "challan"):
            ingest._set_due(conn, inv)
    return {"review": problems, "mismatches": mismatches}


def resolve_review(conn, tenant_id, invoice_id, actor: str) -> None:
    """A person has looked at an invoice in needs review and returns it to verified."""
    service.move_state(conn, tenant_id, invoice_id, "verified", service.today(conn), actor,
                       {"manual_review": True})
