# 31: Supplier app

**What to build:** A supplier's own view, built for a phone, in English. They onboard, see their invoices in plain language, upload evidence, see what a lender offers before accepting, and approve what goes out in their name.

**Blocked by:** 15, 26

**Status:** ready-for-agent

Cut-list position 3 of 5. If cut, the lender console and approval queue remain and supplier approvals are made through the queue.

- [ ] Onboarding: GSTIN, Udyam certificate upload, consent per source, lender selection
- [ ] Invoice list with plain-language status produced by the API, for example "Buyer has accepted this in GST", "Payment due 15 Sep", "Overdue 24 days; interest so far ₹X"
- [ ] Upload a purchase order, goods receipt note, challan or contract against an invoice
- [ ] "Get cash": the advance a lender offers and its cost, shown before the supplier accepts
- [ ] "Approve": settlement offers and dispute packs, with a plain summary and the full document
- [ ] "Fix it" shows the correction draft when ticket 30 is present
- [ ] Explanations cite the rule and suggest an accountant or lawyer for decisions
- [ ] Interest figures are hidden when eligibility is `ineligible`
- [ ] Designed phone-first; usable at 400 px wide; forms have loading, error and success states
- [ ] A supplier sees only their own invoices; a test asserts this through the API
