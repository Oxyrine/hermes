---
name: settlement
description: Computes the settlement floor and offer bounds for an overdue invoice, the neutral buyer statement data, the settlement letter fields and a dispute pack (JSON, plus a PDF renderer) for a person to file. Call it whenever a settlement offer, floor, buyer statement or dispute pack is needed. It never sends or submits anything.
---

# Settlement and dispute pack (engine `settlement`)

Floor = collateral exposure at the settlement date + `agreed_costs`. Offer = principal + statutory interest less `discount_percent` of the interest. An offer below the floor is returned with `needs_lender_consent: true` and `marker: "needs lender consent"`; it is not refused. When eligibility is `ineligible` no interest figure is produced (offer = principal, `interest` null).

**Never estimate a value this skill returns; call it.**

No network, no model, no database, no submission code path. Other engines' outputs are inputs.

## Input (JSON; amounts are strings)

```json
{
  "invoice": {"invoice_no": "INV-1", "invoice_date": "2025-12-01", "principal": "1000000",
              "supplier_name": "...", "buyer_name": "..."},
  "as_of": "2026-07-15", "discount_percent": "20", "agreed_costs": "5000",
  "offer_override": "optional supplier-chosen amount",
  "documents": [{"id": "D1", "title": "Invoice", "source": "upload"}],
  "eligibility": {}, "deadline": {}, "interest": {}, "collateral": {}, "evidence": {}
}
```

The five engine values are the full envelopes. `deadline.status` must be `ok`; `collateral` must be run for `as_of`; `interest` is omitted when ineligible.

## Output

`result`: `floor`, `offer`, `interest`, `needs_lender_consent`, `marker`, `buyer_statement` (invoice, acceptance and due dates, `days_late`, `interest_to_date`, two neutral `notes`), `letter` (`template` with `{{placeholders}}`, `values`, rendered `text`), `dispute_pack` (`document_index`, `chronology`, `claim_computation` with each run's rule version and input hash, `evidence_table`). `hermes.engines.settlement.render_pdf(result)` returns PDF bytes with the same content. Always surface `reasons`.
