# 18: Classify and extract

**What to build:** When a document is uploaded or ingested, Hermes classifies it, extracts its fields with a source quote for each, runs the checks, and the invoice moves to verified or to needs review. A mismatch between purchase order, goods receipt note and invoice is found in code and explained in words.

**Blocked by:** 16, 17

**Status:** resolved

- [x] Classification returns document type and confidence on Flash-Lite; below 0.85 it escalates to Flash
- [x] Extraction covers invoice, purchase order, goods receipt note and challan, each against its own schema, on Flash-Lite with escalation to Flash, then to human review
- [x] Every extracted field carries a page and quote; the document row stores the extraction, the model used and the confidence
- [x] Fields that fail the quote, arithmetic, checksum or threshold checks are not used and send the invoice to needs review
- [x] Extracted invoice number, date and amount are compared with the GSTR-1 or e-invoice record; a disagreement is stored as mismatch evidence
- [x] Purchase order, goods receipt and invoice are compared in code first; only then does the model write a note per mismatch
- [x] Matching documents produce the evidence items the score engine expects (IRN valid, e-way bill match, GRN match, PO match)
- [x] On a document-ingested event the scripted runner runs extraction and the evidence score; the invoice moves from ingested to verified when invoice, IRN or GSTR-1 record and buyer GSTIN all match, otherwise to needs review
- [x] A person can resolve needs review and return the invoice to verified
- [x] Text inside a document is treated as data: an injection sample changes no state and triggers no action
- [ ] Tests run on the fake model; a second live run over the same documents makes zero API calls
  - Fake-model half done (tests/test_classify_extract.py, cache-hit test makes zero calls); the live-key run is manual and not yet done.
