# 32: Buyer statement page

**What to build:** When a settlement offer is approved, a signed link is produced for the buyer. It opens a read-only page showing the invoice, the delivery evidence, the acceptance and due dates and the interest to date, in neutral wording, with a way to pay or respond.

**Blocked by:** 12

**Status:** ready-for-agent

Cut-list position 2 of 5.

- [ ] The link is signed and expires after 30 days; a tampered or expired link shows a plain refusal and no data
- [ ] The link exposes one invoice only and nothing else in the tenant
- [ ] The page shows invoice, delivery evidence, acceptance date, due date, days late and interest to date, all from engine output
- [ ] Two neutral notes only: the tax-deduction deferral and the 75% pre-deposit
- [ ] No threats and no legal conclusions; the page text passes the banned-phrase check
- [ ] A pay-or-respond option records the buyer's reply as an event; no payment is taken by Hermes
- [ ] The page is not indexed by search engines
- [ ] Opening the link adds an audit row
- [ ] A test covers a valid link, an expired link and a tampered link
