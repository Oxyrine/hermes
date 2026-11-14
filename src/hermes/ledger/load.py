"""Load the synthetic world (3 suppliers, 4 buyers, 30 invoices) through the doors live data uses:
onboarding, consent, invoice creation, then every adapter's pull through ingest."""

import json
from datetime import date, timedelta
from pathlib import Path

from hermes.ledger import ingest, onboarding, seed, service, states

PULLS = ("documents", "einvoice", "ims_supplier_view", "gstr1", "ewb", "email", "bank_statement")


def run(conn, root, pull: bool = True) -> dict:
    """Onboard, consent and create invoices; with pull, also run every adapter and verify what
    matched. Without it the world waits for pulls (the API's, in tests)."""
    root = Path(root)
    m = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    tenant, _ = seed.base(conn)
    for b in m["buyers"]:
        conn.execute("INSERT INTO buyer (gstin, legal_name, is_cpse) VALUES (%s,%s,%s)",
                     (b["gstin"], b["name"], b["cpse"]))
    sup, gstin = {}, {b["id"]: b["gstin"] for b in m["buyers"]}
    for s in m["suppliers"]:
        udyam = json.loads((root / f"suppliers/{s['id']}/udyam.truth.json").read_text(encoding="utf-8"))
        sid = sup[s["id"]] = onboarding.onboard_supplier(conn, tenant, {
            "gstin": s["gstin"], "legal_name": s["name"], "udyam_urn": s["urn"],
            "udyam_reg_date": s["reg"], "enterprise_type": s["type"],
            "classifications": {k[6:]: v for k, v in udyam.items() if k.startswith("class_")}})["id"]
        conn.execute("INSERT INTO app_user (tenant_id, email, role, supplier_id) VALUES (%s,%s,'supplier',%s)",
                     (tenant, f"supplier@{s['name'].split()[0].lower()}.example", sid))
        for source in onboarding.SOURCES:
            onboarding.record_consent(conn, tenant, sid, {
                "source": source, "purpose": "servicing",
                "expires_at": str(date.today() + timedelta(days=365))})
    for i in m["invoices"]:
        t = json.loads((root / f"docs/{i['id']}/invoice.truth.json").read_text(encoding="utf-8"))
        onboarding.create_invoice(conn, tenant, {
            "supplier_id": sup[i["supplier"]], "invoice_no": i["invoice_no"],
            "buyer_gstin": gstin[i["buyer"]], "invoice_date": t["invoice_date"],
            "total": f"{t['total']:.2f}", "taxable_value": f"{t['taxable_value']:.2f}",
            "gst_amount": f"{t['gst_amount']:.2f}"})
    if pull:
        for sid in sup.values():
            for source in PULLS:
                ingest.pull(conn, tenant, sid, {"source": source}, root)
        # ponytail: moving matched invoices to verified is the agent's job once extraction exists
        for inv in conn.execute("SELECT id::text FROM invoice").fetchall():
            try:
                service.move_state(conn, tenant, inv[0], "verified", service.today(conn), "loader")
            except states.Refused:
                pass
    return {"tenant": tenant, "suppliers": len(sup), "buyers": len(m["buyers"]),
            "invoices": len(m["invoices"])}
