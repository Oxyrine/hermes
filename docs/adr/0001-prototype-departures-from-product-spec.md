# 0001: Prototype departures from the product spec

Status: accepted. The prototype column of the product spec is built with these departures.

- **Local-first.** PostgreSQL in Docker, local file storage and a DB-backed event queue stand in for Cloud SQL, Cloud Storage and Pub/Sub, behind the interfaces the product spec names.
- **Free-tier models.** Latest free Flash (contract terms, objection detection, mismatch notes, drafting, agent reasoning); Flash-Lite for classification/extraction, escalating to Flash on low confidence. No Pro. Contract terms stay human-confirmed.
- **Loop-first agent.** Gemini function-calling loop built first; a half-day managed-agent spike decides whether demo invoices switch at the end.
- **Schema additions.** Agent runs, consents, users/roles, webhook subscriptions/deliveries, raw records, idempotency keys, event queue, model cache; tenant id on tenant-scoped tables; unlinked/supplier-level documents; action requests gain expiry, reject reason, edit diff, lender-consent; invoices gain agent session ref and stored due date. Plain SQL, no ORM.
- **State-machine additions.** Manual review can return to verified once resolved; financeable can move to overdue.
- **Part-payment convention.** Monthly rests anchored to the interest start date; pro-rata accrual on the running balance within a rest; payment clears accrued interest first, then principal. Equals the product spec formula with no payments. Marked for legal review.
- **GSTR-2B deemed acceptance.** An IMS "no action" counts as deemed accepted only once the buyer's GSTR-2B generation date is on or before the as-of date; before that it is pending.
- **Waterfall.** Receipts cover lender exposure and agreed costs first; the rest, including all statutory interest, goes to the supplier. No interest-linked fee.
- **Injected clock.** Time is injected; a dev-only endpoint sets it and a tick emits deadline-passed/offer-expired events and writes collateral snapshots.
- **Tenancy.** Every query filters by tenant from the start; row-level security is layered on later (cut-list item).
