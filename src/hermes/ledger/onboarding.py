"""Onboarding, consent, invoice creation and document upload. Every input is validated here and
refused with a message a person can act on (ValueError -> 422, states.Refused -> 409)."""

import hashlib
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from psycopg.errors import UniqueViolation
from psycopg.rows import dict_row

from hermes.ledger import states
from hermes.ledger.service import NotFound
from hermes.synthetic.gstin import is_valid_gstin

UDYAM = re.compile(r"^UDYAM-[A-Z]{2}-\d{2}-\d{7}$")
FY = re.compile(r"^(\d{4})-(\d{2})$")
ENTERPRISE_TYPES = ("manufacturing", "services", "trading")
CLASSES = ("micro", "small", "medium")
SOURCES = ("ims_supplier_view", "gstr1", "einvoice", "bank_statement", "email")
PURPOSES = ("underwriting", "servicing", "dispute_resolution")
DOC_TYPES = ("invoice", "po", "grn", "challan", "contract", "email", "debit_note", "bank_stmt",
             "certificate")
SUPPLIER_DOC_TYPES = ("certificate", "contract")
MAX_UPLOAD = 5 * 1024 * 1024
# content type -> leading bytes the file must start with (a mislabelled file is refused)
SIGNATURES = {"application/pdf": (b"%PDF-",), "image/png": (b"\x89PNG\r\n\x1a\n",),
              "image/jpeg": (b"\xff\xd8\xff",), "image/webp": (b"RIFF",)}


def _text(body: dict, key: str, label: str, limit: int = 200) -> str:
    v = body.get(key)
    if not isinstance(v, str) or not v.strip():
        raise ValueError(f"{label} is required")
    if len(v) > limit:
        raise ValueError(f"{label} is longer than {limit} characters")
    return v.strip()


def _date(v, label: str) -> date:
    try:
        return date.fromisoformat(v)
    except (TypeError, ValueError):
        raise ValueError(f"{label} must be a date like 2026-04-01") from None


def _choice(v, options, label: str) -> str:
    if v not in options:
        raise ValueError(f"{label} must be one of: {', '.join(options)}")
    return v


def _money(v, label: str, required: bool = True) -> Decimal | None:
    if v is None and not required:
        return None
    try:
        d = Decimal(v) if isinstance(v, str) else None
        if d is None or not d.is_finite() or d.as_tuple().exponent < -2 or d <= 0 or d >= 10**16:
            raise InvalidOperation
    except InvalidOperation:
        raise ValueError(f"{label} must be a positive amount in rupees with at most 2 decimals, "
                         "sent as a string") from None
    return d


def _uuid(v, what: str) -> str:
    from uuid import UUID
    try:
        return str(UUID(str(v)))
    except ValueError:
        raise NotFound(what) from None


def onboard_supplier(conn, tenant_id, body: dict) -> dict:
    gstin = _text(body, "gstin", "GSTIN").upper()
    if not is_valid_gstin(gstin):
        raise ValueError("GSTIN is not valid: it must be 15 characters and pass the checksum")
    name = _text(body, "legal_name", "legal name")
    urn = _text(body, "udyam_urn", "Udyam number").upper()
    if not UDYAM.match(urn):
        raise ValueError("Udyam number must look like UDYAM-MH-26-0001234")
    reg = _date(body.get("udyam_reg_date"), "Udyam registration date")
    kind = _choice(body.get("enterprise_type"), ENTERPRISE_TYPES, "enterprise type")
    cls = body.get("classifications")
    if not isinstance(cls, dict) or not cls:
        raise ValueError("classifications is required: a class for each financial year")
    for fy, c in cls.items():
        m = FY.match(str(fy))
        if not m or (int(m[1]) + 1) % 100 != int(m[2]):
            raise ValueError(f"financial year {fy!r} must look like 2026-27")
        _choice(c, CLASSES, f"classification for {fy}")
    try:
        sid = conn.execute(
            "INSERT INTO supplier (tenant_id, gstin, legal_name, udyam_urn, udyam_reg_date, "
            "enterprise_type, onboarded_at) VALUES (%s,%s,%s,%s,%s,%s, now()) RETURNING id::text",
            (tenant_id, gstin, name, urn, reg, kind)).fetchone()[0]
    except UniqueViolation:
        raise states.Refused("a supplier with this GSTIN is already onboarded") from None
    for fy, c in cls.items():
        conn.execute("INSERT INTO udyam_classification (supplier_id, tenant_id, fy, class) "
                     "VALUES (%s,%s,%s,%s)", (sid, tenant_id, fy, c))
    return {"id": sid, "gstin": gstin, "legal_name": name}


def _own_supplier(conn, tenant_id, supplier_id, only_supplier):
    sid = _uuid(supplier_id, "supplier")
    if only_supplier is not None and only_supplier != sid:
        raise NotFound("supplier")
    if not conn.execute("SELECT 1 FROM supplier WHERE id=%s AND tenant_id=%s",
                        (sid, tenant_id)).fetchone():
        raise NotFound("supplier")
    return sid


_CONSENT = ("SELECT c.id::text, c.supplier_id::text, c.source, c.purpose, t.name AS lender, "
            "c.granted_at, c.expires_at::date::text AS expires_at, c.revoked_at AS withdrawn_at "
            "FROM consent c JOIN tenant t ON t.id=c.tenant_id ")


def record_consent(conn, tenant_id, supplier_id, body: dict, only_supplier=None) -> dict:
    sid = _own_supplier(conn, tenant_id, supplier_id, only_supplier)
    source = _choice(body.get("source"), SOURCES, "source")
    purpose = _choice(body.get("purpose"), PURPOSES, "purpose")
    expires = _date(body.get("expires_at"), "expiry")
    if expires <= date.today():
        raise ValueError("expiry must be a future date")
    cid = conn.execute("INSERT INTO consent (tenant_id, supplier_id, source, purpose, expires_at) "
                       "VALUES (%s,%s,%s,%s,%s) RETURNING id", (tenant_id, sid, source, purpose,
                       datetime.combine(expires, datetime.min.time()))).fetchone()[0]
    return conn.cursor(row_factory=dict_row).execute(_CONSENT + "WHERE c.id=%s", (cid,)).fetchone()


def withdraw_consent(conn, tenant_id, supplier_id, consent_id, only_supplier=None) -> dict:
    sid = _own_supplier(conn, tenant_id, supplier_id, only_supplier)
    cid = _uuid(consent_id, "consent")
    if not conn.execute("UPDATE consent SET revoked_at=COALESCE(revoked_at, now()) "
                        "WHERE id=%s AND supplier_id=%s RETURNING 1", (cid, sid)).fetchone():
        raise NotFound("consent")
    return conn.cursor(row_factory=dict_row).execute(_CONSENT + "WHERE c.id=%s", (cid,)).fetchone()


def list_consents(conn, tenant_id, supplier_id, only_supplier=None) -> list[dict]:
    sid = _own_supplier(conn, tenant_id, supplier_id, only_supplier)
    return conn.cursor(row_factory=dict_row).execute(
        _CONSENT + "WHERE c.supplier_id=%s ORDER BY c.granted_at", (sid,)).fetchall()


def create_invoice(conn, tenant_id, body: dict, only_supplier=None) -> dict:
    sid = _own_supplier(conn, tenant_id, only_supplier or body.get("supplier_id"), only_supplier)
    no = _text(body, "invoice_no", "invoice number", 50)
    gst = _text(body, "buyer_gstin", "buyer GSTIN").upper()
    if not is_valid_gstin(gst):
        raise ValueError("buyer GSTIN is not valid: it must be 15 characters and pass the checksum")
    buyer = conn.execute("SELECT id FROM buyer WHERE gstin=%s", (gst,)).fetchone()
    if not buyer:
        raise ValueError("buyer GSTIN is not a known buyer")
    day = _date(body.get("invoice_date"), "invoice date")
    total = _money(body.get("total"), "total")
    taxable = _money(body.get("taxable_value"), "taxable value", required=False)
    tax = _money(body.get("gst_amount"), "GST amount", required=False)
    try:
        iid = conn.execute(
            "INSERT INTO invoice (tenant_id, supplier_id, buyer_id, invoice_no, invoice_date, "
            "taxable_value, gst_amount, total, state, state_changed_at) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'ingested', now()) RETURNING id::text",
            (tenant_id, sid, buyer[0], no, day, taxable, tax, total)).fetchone()[0]
    except UniqueViolation:
        raise states.Refused(f"invoice {no} already exists for this supplier") from None
    return {"id": iid, "invoice_no": no, "state": "ingested"}
