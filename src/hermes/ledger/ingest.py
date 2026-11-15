# ruff: noqa: C408
"""Ingest what the adapters fetch. Each raw record is stored unchanged, matched to one of the
supplier's invoices (GSTINs, invoice number, date, amount), and only an exact match is normalised
into IMS events, evidence items, documents or payments and announced to the invoice's agent. A
partial match becomes a review action and links nothing; a record that matches nothing stays raw."""

import base64
import hashlib
import json
import re
from datetime import datetime
from decimal import Decimal

from hermes import adapters
from hermes.engines import deadline
from hermes.ledger import onboarding, service

REVIEW_FLOOR = 0.5  # share of the record's fields that must agree for a person to be asked
KEYS = ("invoice_no", "buyer_gstin", "date", "amount")
IMS = {"A": "accepted", "R": "rejected", "P": "pending", "N": "no_action"}
DOC_TYPES = {"invoice": "invoice", "purchase_order": "po", "goods_receipt_note": "grn",
             "delivery_challan": "challan", "contract": "contract"}
EVENTS = {"ims_supplier_view": "ims.action_changed", "bank_statement": "payment.received",
          "documents": "document.ingested", "email": "document.ingested"}  # else source.record.ingested


class Mismatch(Exception):
    """A record matched an invoice but failed a check on it; a person looks at it."""


def _d(s: str) -> str:
    return datetime.strptime(s.replace("/", "-")[:10], "%d-%m-%Y").date().isoformat()


def _fields(conn, source: str, p: dict) -> dict:
    """The fields a record offers for matching, in the matcher's terms."""
    if source in ("ims_supplier_view", "gstr1"):
        return dict(invoice_no=p["inum"], buyer_gstin=p["ctin"], date=_d(p["idt"]), amount=p["val"])
    if source == "ewb":
        return dict(invoice_no=p["docNo"], buyer_gstin=p["toGstin"], date=_d(p["docDate"]),
                    amount=p["totInvValue"])
    if source == "einvoice":
        c = adapters.qr_claims(p["qr"])[0]
        return dict(invoice_no=c["DocNo"], buyer_gstin=c["BuyerGstin"], date=_d(c["DocDt"]),
                    amount=c["TotInvVal"])
    if source == "bank_statement":  # statements name the payer, not its GSTIN
        g = conn.execute("SELECT gstin FROM buyer WHERE legal_name=%s", (p["counterparty"],)).fetchone()
        return dict(buyer_gstin=g[0] if g else "UNKNOWN", amount=p["amount"])
    if source == "documents":
        return dict(invoice_no=p["invoice_no"], buyer_gstin=p["fields"]["buyer_gstin"])
    return dict(invoice_no=re.search(r"Invoice (\S+)$", p["messages"][0]["subject"])[1])  # email


def _norm(key: str, v):
    if key == "amount":
        return Decimal(str(v)).quantize(Decimal("0.01"))
    return re.sub(r"[^A-Z0-9]", "", str(v).upper()) if key == "invoice_no" else str(v).upper()


def match(conn, tenant_id, supplier_id, f: dict) -> tuple[str, str | None, float, list[str]]:
    """('linked' | 'review' | 'unmatched', invoice id, score, candidate invoice numbers)."""
    scored = []
    for r in conn.execute(
            "SELECT i.id::text, i.invoice_no, b.gstin, i.invoice_date::text, i.total FROM invoice i "
            "JOIN buyer b ON b.id=i.buyer_id WHERE i.tenant_id=%s AND i.supplier_id=%s "
            "ORDER BY i.invoice_no", (tenant_id, supplier_id)).fetchall():
        agree = [_norm(k, f[k]) == _norm(k, v) for k, v in zip(KEYS, r[1:], strict=True)
                 if f.get(k) is not None]
        scored.append((sum(agree) / len(agree), r[0], r[1]))
    if not scored:
        return "unmatched", None, 0.0, []
    top = max(s[0] for s in scored)
    best = [s for s in scored if s[0] == top]
    names = [s[2] for s in best]
    if top == 1 and len(best) == 1:
        return "linked", best[0][1], top, names
    return ("review" if top >= REVIEW_FLOOR else "unmatched"), best[0][1], top, names


def _evidence(conn, tenant_id, inv, signal, source_ref, value=None):
    conn.execute("INSERT INTO evidence_item (tenant_id, invoice_id, signal, value, source_ref, "
                 "detected_at) VALUES (%s,%s,%s,%s::jsonb,%s::jsonb, now())",
                 (tenant_id, inv, signal, value and json.dumps(value), json.dumps(source_ref)))


def _set_due(conn, inv):
    """Write the stored due date from the deadline engine once delivery is known."""
    row = conn.execute(
        "SELECT (SELECT extracted->>'delivery_date' FROM document WHERE invoice_id=i.id AND "
        "extracted->>'delivery_date' IS NOT NULL ORDER BY doc_type LIMIT 1), "
        "(SELECT written_payment_days FROM contract WHERE id=i.contract_id) FROM invoice i "
        "WHERE i.id=%s", (inv,)).fetchone()
    if row[0]:
        due = deadline.run({"delivery": row[0], "written_days": row[1]})["result"]["due"]
        conn.execute("UPDATE invoice SET due_date=%s WHERE id=%s", (due, inv))


def _contract(conn, tenant_id, inv, signed, days=None, terms=None):
    # ponytail: one contract per invoice; a supplier-buyer contract once terms are confirmed by a person
    cid = conn.execute("SELECT contract_id FROM invoice WHERE id=%s", (inv,)).fetchone()[0]
    if cid is None:
        cid = conn.execute(
            "INSERT INTO contract (tenant_id, supplier_id, buyer_id, signed_date, written_payment_days, "
            "terms_source) SELECT %s, supplier_id, buyer_id, %s, %s, %s::jsonb FROM invoice WHERE id=%s "
            "RETURNING id", (tenant_id, signed, days, terms and json.dumps(terms), inv)).fetchone()[0]
        conn.execute("UPDATE invoice SET contract_id=%s WHERE id=%s", (cid, inv))
    else:
        conn.execute("UPDATE contract SET signed_date=%s, written_payment_days=%s, terms_source=%s::jsonb "
                     "WHERE id=%s", (signed, days, terms and json.dumps(terms), cid))


def _ims(conn, t, inv, rec, raw, f):
    p, action = rec.payload, IMS[rec.payload["action"]]
    eid = conn.execute(
        "INSERT INTO ims_event (tenant_id, invoice_id, action, action_at, raw_ref, fetched_at) "
        "VALUES (%s,%s,%s,%s,%s,%s) RETURNING id",
        (t, inv, action, _d(p["actndt"]) if p.get("actndt") else None, raw, rec.fetched_at)).fetchone()[0]
    _evidence(conn, t, inv, f"ims_{action}", {"raw_id": raw, "ims_event_id": eid},
              {"gstr2b_generated": _d(p["gstr2b_gendt"])} if action == "no_action" else None)
    if action == "rejected":
        service.raise_hard_flag(conn, t, inv, "ims_rejection", {"ims_event_id": eid, "raw_id": raw})


def _ewb(conn, t, inv, rec, raw, f):
    conn.execute("UPDATE invoice SET ewb_no=%s WHERE id=%s", (str(rec.payload["ewbNo"]), inv))
    _evidence(conn, t, inv, "ewb_matching", {"ewb_no": str(rec.payload["ewbNo"]), "raw_id": raw})


def _einvoice(conn, t, inv, rec, raw, f):
    claims, signed = adapters.qr_claims(rec.payload["qr"])
    known = conn.execute(
        "SELECT COALESCE(i.irn, (SELECT extracted->>'irn' FROM document WHERE invoice_id=i.id AND "
        "doc_type='invoice' LIMIT 1)) FROM invoice i WHERE i.id=%s", (inv,)).fetchone()[0]
    if not signed or known not in (None, claims["Irn"]):
        raise Mismatch("the e-invoice QR signature or IRN does not check out against the invoice")
    conn.execute("UPDATE invoice SET irn=%s WHERE id=%s", (claims["Irn"], inv))
    _evidence(conn, t, inv, "irn_valid_matching", {"irn": claims["Irn"], "raw_id": raw})


def _bank(conn, t, inv, rec, raw, f):
    p = rec.payload
    conn.execute("INSERT INTO payment (tenant_id, invoice_id, amount, paid_on, utr, source, raw_id) "
                 "VALUES (%s,%s,%s,%s,%s,'bank_statement',%s)",
                 (t, inv, p["amount"], p["date"], p["utr"], raw))


def _store(conn, t, inv, doc_type, name, ctype, data, extracted, raw) -> str:
    return conn.execute(
        "INSERT INTO document (tenant_id, invoice_id, supplier_id, doc_type, filename, content_type, "
        "size_bytes, content, sha256, extracted, raw_id) SELECT %s,%s,supplier_id,%s,%s,%s,%s,%s,%s,"
        "%s::jsonb,%s FROM invoice WHERE id=%s RETURNING id::text",
        (t, inv, doc_type, name, ctype, len(data), data, hashlib.sha256(data).hexdigest(),
         extracted and json.dumps(extracted), raw, inv)).fetchone()[0]


def _documents(conn, t, inv, rec, raw, f):
    p = rec.payload
    fields, kind = dict(p["fields"]), DOC_TYPES[p["fields"]["doc_type"]]
    if kind in ("grn", "challan"):  # stand-in for extraction until the model layer reads the PDF
        fields["delivery_date"] = fields[f"{kind}_date"]
    did = _store(conn, t, inv, kind, p["filename"], p["content_type"],
                 base64.b64decode(p["content_b64"]), fields, raw)
    if kind in ("po", "grn"):
        _evidence(conn, t, inv, f"{kind}_matching", {"document_id": did, "doc_type": kind, "raw_id": raw})
    if kind == "po":
        _contract(conn, t, inv, fields["po_date"])
    if kind == "contract":
        days = fields.get("payment_days")
        _contract(conn, t, inv, fields["signed_date"], days,
                  days and {"doc_id": did, "page": fields["page"], "quote": fields["clause_quote"]})
    if kind in ("grn", "challan", "contract"):
        _set_due(conn, inv)


def _email(conn, t, inv, rec, raw, f):
    _store(conn, t, inv, "email", rec.external_id + ".json", "application/json",
           json.dumps(rec.payload).encode(), None, raw)


NORMALISE = {"ims_supplier_view": _ims, "ewb": _ewb, "einvoice": _einvoice, "bank_statement": _bank,
             "documents": _documents, "email": _email, "gstr1": lambda *a: None}  # GSTR-1: raw, linked, announced


def _ingest(conn, tenant_id, supplier_id, rec: adapters.RawRecord) -> str:
    digest = hashlib.sha256(json.dumps(rec.payload, sort_keys=True).encode()).hexdigest()
    with conn.transaction():
        row = conn.execute(
            "INSERT INTO raw_record (tenant_id, supplier_id, source, external_id, payload, sha256, "
            "fetched_at, consent_id) VALUES (%s,%s,%s,%s,%s::jsonb,%s,%s,%s) "
            "ON CONFLICT (tenant_id, source, sha256) DO NOTHING RETURNING id::text",
            (tenant_id, supplier_id, rec.source, rec.external_id, json.dumps(rec.payload), digest,
             rec.fetched_at, rec.consent_id)).fetchone()
        if row is None:
            return "duplicate"
        raw, f = row[0], _fields(conn, rec.source, rec.payload)
        status, inv, score, names = match(conn, tenant_id, supplier_id, f)
        reason = None
        try:
            if status == "linked":
                NORMALISE[rec.source](conn, tenant_id, inv, rec, raw, f)
        except Mismatch as e:
            status, reason = "review", str(e)
        if status == "review":
            service.propose_action(conn, tenant_id, inv, "doc_link", {
                "source": rec.source, "raw_id": raw, "external_id": rec.external_id,
                "score": score, "candidates": names, "reason": reason, "fields": {k: str(v) for k, v in f.items()}},
                f"adapter:{rec.source}")
        if status == "linked":
            as_of = rec.payload["date"] if rec.source == "bank_statement" else service.today(conn).isoformat()
            conn.execute("INSERT INTO event_queue (tenant_id, invoice_id, kind, payload) "
                         "VALUES (%s,%s,%s,%s::jsonb)",
                         (tenant_id, inv, EVENTS.get(rec.source, "source.record.ingested"),
                          json.dumps({"source": rec.source, "raw_id": raw, "as_of": as_of})))
    return status


def pull(conn, tenant_id, supplier_id, body: dict, root, only_supplier=None) -> dict:
    """Fetch one source for one supplier under their consent and ingest every record."""
    sid = onboarding._own_supplier(conn, tenant_id, supplier_id, only_supplier)
    source = onboarding._choice(body.get("source"), adapters.READERS, "source")
    purpose = onboarding._choice(body.get("purpose", "servicing"), onboarding.PURPOSES, "purpose")
    records = adapters.FixtureAdapter(source, conn, tenant_id, purpose, root,
                                      body.get("fixture")).fetch(sid)
    out = {"source": source, "fetched": len(records), "linked": 0, "review": 0, "unmatched": 0,
           "duplicate": 0}
    for r in records:
        out[_ingest(conn, tenant_id, sid, r)] += 1
    return out

