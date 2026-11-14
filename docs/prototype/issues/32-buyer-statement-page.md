# 32: Buyer statement page

**What to build:** When a settlement offer is approved, a signed link is produced for the buyer. It opens a read-only page showing the invoice, the delivery evidence, the acceptance and due dates and the interest to date, in neutral wording, with a way to pay or respond.

**Blocked by:** 12

**Status:** resolved

Cut-list position 2 of 5.

- [x] The link is signed and expires after 30 days; a tampered or expired link shows a plain refusal and no data
- [x] The link exposes one invoice only and nothing else in the tenant
- [x] The page shows invoice, delivery evidence, acceptance date, due date, days late and interest to date, all from engine output
- [x] Two neutral notes only: the tax-deduction deferral and the 75% pre-deposit
- [x] No threats and no legal conclusions; the page text passes the banned-phrase check
- [x] A pay-or-respond option records the buyer's reply as an event; no payment is taken by Hermes
- [x] The page is not indexed by search engines
- [x] Opening the link adds an audit row
- [x] A test covers a valid link, an expired link and a tampered link
