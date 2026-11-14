# 13: Audit, idempotency, roles

**What to build:** Every change to the ledger is traceable to an actor, a retried request never writes twice, and each endpoint refuses callers without the right role.

**Blocked by:** 12

**Status:** resolved

- [x] Every write through the API adds an audit row with time, actor, action, object and before and after values
- [x] The audit log and the IMS event table reject updates and deletes at the database level
- [x] A write repeated with the same idempotency key returns the first response and writes nothing new
- [x] Roles are lender operations, lender approver, supplier, Hermes operations and agent; each endpoint in the product spec (§8) accepts only the roles listed for it
- [x] Only a lender role can record an advance; only an approver role can approve; the agent role cannot approve anything
- [x] A supplier user sees only their own supplier's invoices
- [x] Reads of sensitive data (bank receipts, documents) add an audit row
- [x] The late-buyer scenario still passes
