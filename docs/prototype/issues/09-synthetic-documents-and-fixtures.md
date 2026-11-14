# 09: Synthetic documents and fixtures

**What to build:** One command generates the whole synthetic world as files: 3 suppliers, 4 buyers and 30 invoices, with their documents, emails, bank statements and GST records, each with ground truth beside it. The files follow the GSTN sandbox response shapes and the product spec's extraction schema, not the database schema; loading them into the ledger is ticket 16.

**Blocked by:** 01

**Status:** resolved

- [ ] Generation is deterministic: the same seed gives byte-identical output
- [ ] Per invoice: an invoice PDF with a text layer and a test-signed e-invoice QR; where the scenario calls for them, a purchase order, goods receipt note, challan, contract and Udyam certificate
- [ ] Every document has a ground-truth file matching the product spec's extraction schema (§6), including a page and exact quote for each field
- [ ] 20 email threads: objections within 15 days, objections after 15 days, payment delays, document requests and noise, each labelled
- [ ] A handful of documents and emails with planted instructions, labelled as injection samples
- [ ] Bank statement PDFs with credits from buyers (UTR, date, amount), including part payments
- [ ] IMS Supplier View records shaped like GSTN sandbox responses, covering accepted, rejected, pending and no action; every record carries the buyer's GSTR-2B generation date for its period
- [ ] GSTR-1 records, including at least one invoice filed in the B2C table by mistake
- [ ] E-way bill records
- [ ] Each of the six end-to-end scenarios in the product spec (§12) has at least one invoice laid out for it, and a manifest names which
- [ ] GSTINs carry valid checksums; all names, numbers and addresses are invented
- [ ] A manifest lists the SHA-256 hash of every generated document (used later by the synthetic-only guard)
