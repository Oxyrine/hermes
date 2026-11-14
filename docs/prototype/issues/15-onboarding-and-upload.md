# 15: Onboarding and upload

**What to build:** A lender onboards a supplier with GSTIN and Udyam details. The supplier records consent per data source and purpose, creates an invoice and uploads documents against it. Uploaded files are stored unchanged and announce themselves as events.

**Blocked by:** 13

**Status:** resolved

- [x] Onboarding validates the GSTIN checksum and stores Udyam number, registration date, enterprise type and per-year classification
- [x] A consent names the source, purpose, lender and expiry; consents can be withdrawn
- [x] Creating an invoice enforces uniqueness of supplier and invoice number and starts in state ingested
- [x] Upload accepts PDF and common image types only, enforces a size limit, stores the file unchanged with its SHA-256 hash, and never serves it back without an authorised request
- [x] A document can be supplier-level (certificate, contract) or linked to an invoice
- [x] Each upload publishes a document-ingested event
- [x] All input is validated at the API boundary with clear error messages
- [x] Minimal forms exist for onboarding, consent and upload, with loading, error and success states
- [x] Tests through the API cover a bad GSTIN, a duplicate invoice number, a refused file type and a successful upload
