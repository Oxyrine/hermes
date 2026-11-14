# 20: Model-read facts with human confirmation (objections, contract terms)

**What to build:** Two facts that move a legal date are read by a model and confirmed by a person before they count. A buyer's written objection is detected in an email or debit note; a contract's payment term is read with its clause. In both cases nothing changes until a named person confirms, and then the deadline, interest and collateral recompute. Covers scenario 4.

**Blocked by:** 18

**Status:** ready-for-agent

- [ ] Objection detection uses the instruction from the product spec (§6) on Flash and returns whether it is an objection, the date raised, the exact quote, the invoice references and a confidence
- [ ] A payment delay, a request for documents or a general complaint is not flagged as an objection
- [ ] A detected objection creates a confirmation action showing the quote and proposed date; until it is approved no deadline changes and no skill re-runs
- [ ] Confirming an objection needs both Hermes operations and the supplier
- [ ] On confirmation the deadline, interest and collateral re-run; an objection within 15 days of delivery moves the acceptance date; the evidence score takes the −20 and the hard flag
- [ ] Contract terms are read on Flash (no Pro model) and return payment days, the event they run from, the clause quote and the page
- [ ] A read contract term creates a confirmation action; only after Hermes operations confirms is it stored on the contract with who and when, and used by the deadline engine
- [ ] The approver can correct the date or the term before confirming; the correction is recorded
- [ ] Scenario 4 passes: a buyer email disputes quality on day 9, a person confirms, acceptance and due date move, collateral is recomputed
- [ ] On the 20 synthetic threads with the fake model, every labelled objection is surfaced for confirmation
