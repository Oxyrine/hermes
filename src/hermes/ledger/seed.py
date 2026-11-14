"""Hand-seeded world for the first slice: one lender, one supplier, one buyer, one verified invoice.

`python -m hermes.ledger.seed` resets the database named by DATABASE_URL and seeds it
(development only).
"""

import json

import psycopg

from hermes.synthetic.gstin import gstin_checksum

# Bank rate rows. Each carries the page it was read from; none is written from memory.
# 2025-12-05: RBI press release 2025-2026/1633 sets the Bank Rate to 5.50 per cent. The release
# states no separate effective date; its release date is used.
# 2026-10-07: 5.75 per cent per the product spec's reference (TaxGuru reproduction of RBI press
# release 2026-2027/1264, dated 7 October 2026).
BANK_RATES = [
    ("2025-12-05", "5.50", "https://www.rbi.org.in/Scripts/BS_PressReleaseDisplay.aspx?prid=61749"),
    ("2026-10-07", "5.75", "https://taxguru.in/?p=1087330"),
]


def _gstin(first14: str) -> str:
    return first14 + gstin_checksum(first14)


def run(conn: psycopg.Connection) -> dict:
    def one(sql, *args):
        return conn.execute(sql, args).fetchone()[0]

    tenant = one("INSERT INTO tenant (name, kind, max_ltv, lender_rate_nominal) "
                 "VALUES ('Lender A (synthetic)', 'nbfc', 0.8000, 18.000000) RETURNING id")
    users = {
        role: one("INSERT INTO app_user (tenant_id, email, role) VALUES (%s,%s,%s) RETURNING id",
                  tenant, f"{name}@lender-a.example", role)
        for name, role in (("ops", "lender_ops"), ("approver", "lender_approver"),
                           ("agent", "agent"), ("supplier", "supplier"))
    }
    for d, rate, url in BANK_RATES:
        conn.execute("INSERT INTO bank_rate (effective_from, rate, source_url, entered_by, "
                     "approved_by) VALUES (%s,%s,%s,%s,%s)",
                     (d, rate, url, users["lender_ops"], users["lender_approver"]))

    supplier = one(
        "INSERT INTO supplier (tenant_id, gstin, legal_name, udyam_urn, udyam_reg_date, "
        "enterprise_type, onboarded_at) VALUES (%s,%s,'Sundaram Fabrication Works (synthetic)',"
        "'UDYAM-KA-18-0002002','2021-04-01','manufacturing', now()) RETURNING id",
        tenant, _gstin("29AABCS0002A1Z"))
    conn.execute("INSERT INTO app_user (tenant_id, email, role, supplier_id) "
                 "VALUES (%s,'supplier@sundaram.example','supplier',%s)", (tenant, supplier))
    conn.execute("INSERT INTO udyam_classification (supplier_id, tenant_id, fy, class) "
                 "VALUES (%s,%s,'2026-27','small')", (supplier, tenant))
    buyer = one("INSERT INTO buyer (gstin, legal_name) VALUES (%s,'Meridian Heavy Engineering "
                "Ltd (synthetic)') RETURNING id", _gstin("29AABCM0001B1Z"))
    contract = one(
        "INSERT INTO contract (tenant_id, supplier_id, buyer_id, signed_date, "
        "written_payment_days, terms_source, terms_confirmed_by, terms_confirmed_at) "
        "VALUES (%s,%s,%s,'2026-05-10',45,%s::jsonb,%s, now()) RETURNING id",
        tenant, supplier, buyer,
        json.dumps({"page": 2, "quote": "Payment within 45 days of receipt of goods."}),
        users["lender_ops"])
    invoice = one(
        "INSERT INTO invoice (tenant_id, supplier_id, buyer_id, contract_id, invoice_no, "
        "invoice_date, taxable_value, gst_amount, total, irn, ewb_no, state, state_changed_at, "
        "due_date) VALUES (%s,%s,%s,%s,'AC/2026/0412','2026-07-28',847457.63,152542.37,"
        "1000000.00,'a1b2c3-synthetic-irn','341000000001','verified', now(),'2026-09-15') "
        "RETURNING id", tenant, supplier, buyer, contract)

    def doc(doc_type, extracted):
        return one("INSERT INTO document (tenant_id, invoice_id, supplier_id, doc_type, extracted) "
                   "VALUES (%s,%s,%s,%s,%s::jsonb) RETURNING id",
                   tenant, invoice, supplier, doc_type, json.dumps(extracted))

    po, grn = doc("po", {"po_no": "PO-7781"}), doc("grn", {"delivery_date": "2026-08-01"})
    ims = conn.execute(
        "INSERT INTO ims_event (tenant_id, invoice_id, action, action_at, raw_ref, fetched_at) "
        "VALUES (%s,%s,'accepted','2026-08-20T10:00:00+05:30','ims:synthetic:2026-08',now()) "
        "RETURNING id", (tenant, invoice)).fetchone()[0]
    for signal, source in (
        ("irn_valid_matching", {"irn": "a1b2c3-synthetic-irn"}),
        ("ewb_matching", {"ewb_no": "341000000001"}),
        ("grn_matching", {"document_id": str(grn), "doc_type": "grn"}),
        ("po_matching", {"document_id": str(po), "doc_type": "po"}),
        ("ims_accepted", {"ims_event_id": ims}),
    ):
        conn.execute("INSERT INTO evidence_item (tenant_id, invoice_id, signal, source_ref, "
                     "detected_at) VALUES (%s,%s,%s,%s::jsonb, now())",
                     (tenant, invoice, signal, json.dumps(source)))
    return {"tenant": tenant, "supplier": supplier, "buyer": buyer, "invoice": invoice}


if __name__ == "__main__":
    from hermes.ledger import db

    with psycopg.connect(db.database_url(), autocommit=True) as c:
        db.reset(c)
        print(run(c))
