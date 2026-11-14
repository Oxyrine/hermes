# 16: Fixture adapters, loading and matching

**What to build:** The synthetic world is loaded into the ledger through the same door live data will use. Each source (IMS Supplier View, GSTR-1, e-way bill, bank statements, documents, email) has an adapter that fetches raw records; records are stored unchanged, matched to invoices, and turned into IMS events, evidence items and payments.

**Blocked by:** 09, 15

**Status:** ready-for-agent

- [ ] Every adapter implements the one fetch interface from the product spec (§3) and returns raw records carrying source, external id, payload, fetch time and the consent that covered the pull
- [ ] An adapter refuses to fetch when no live consent exists for that source and purpose
- [ ] Raw payloads are stored unchanged and never edited; normalised rows point back to them
- [ ] Each ingested record publishes an event routed to its invoice
- [ ] Matching uses GSTINs, invoice number, date and amount; an exact match links; a fuzzy match below threshold creates a review action and does not link
- [ ] IMS events are append-only: a reversal is a new row
- [ ] An IMS change triggers evidence score and collateral re-runs
- [ ] The e-invoice QR is decoded from the invoice PDF and its IRN checked against the invoice
- [ ] Bank credits become payments on the matched invoice and trigger interest and collateral re-runs; an invoice whose receipts cover the amount due moves to paid
- [ ] One command loads the whole synthetic set: 3 suppliers, 4 buyers, 30 invoices
- [ ] The seed-and-reset command and the late-buyer demo now run on the synthetic set
- [ ] Tests through the API cover an exact match, a fuzzy match going to review, a missing consent, and reconciliation to paid
