# 10: A seeded invoice you can read

**What to build:** A lender user logs in on the development login, opens one hand-seeded verified invoice, and sees its evidence contributions, deadline working and claim, all computed by the engines. First cut through every layer: schema, seed, API, page.

**Blocked by:** 03, 04, 05, 06, 07

**Status:** ready-for-agent

- [ ] Schema is the product spec's tables (§4) plus the additions in this feature's spec: tenant id on every tenant-scoped table, agent runs, consents, users and roles, raw records, idempotency keys, event queue, model cache, webhook subscriptions and deliveries; nullable invoice link and a supplier link on documents; expiry, reject reason, edit difference and lender-consent fields on action requests; agent session and stored due date on invoices
- [ ] Money columns are NUMERIC(18,2), rates NUMERIC(9,6), dates are IST dates
- [ ] A seed creates one lender tenant, one supplier, one buyer, one verified invoice with evidence items, and approved bank-rate rows. 5.75% from 7 October 2026 comes from the product spec's reference; earlier rows are looked up from RBI releases and carry a source link, not written from memory
- [ ] Development login issues a signed token carrying tenant and role for a chosen seeded user; it exists only in the development environment
- [ ] Every query filters by the caller's tenant
- [ ] Running an engine through the API stores an engine run with rule version, inputs hash, inputs and outputs
- [ ] Invoice read returns state, eligibility, deadline, claim, evidence and collateral in the shape of the product spec's example (§8)
- [ ] Invoice page shows evidence contributions with sources, the deadline working and the claim; no money arithmetic happens in the browser
- [ ] A test through the API asserts the seeded invoice's figures equal the engines' outputs
