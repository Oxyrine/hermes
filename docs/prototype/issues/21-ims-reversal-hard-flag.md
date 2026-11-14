# 21: IMS reversal hard flag

**What to build:** A buyer who accepted an invoice in IMS changes it to rejected after the lender has funded. The lender sees a hard flag at once, the score drops, and the invoice is sent for review. Covers scenario 6 except the webhook, which is ticket 33.

**Blocked by:** 16

**Status:** ready-for-agent

- [ ] The reversal arrives as a new IMS event; the earlier acceptance remains in the history
- [ ] The evidence score re-runs: the +25 is replaced by −30 and a hard flag
- [ ] The collateral engine raises its "hard flag after funding" alert
- [ ] The invoice is marked for review whatever its score; a review action is proposed
- [ ] The flag and alert appear on the invoice page and in the timeline
- [ ] A hard-flag event is recorded for later delivery to the lender
- [ ] A debit note against a funded invoice and a confirmed objection on a funded invoice raise the same flag path
- [ ] Scenario 6 passes up to, but not including, the webhook assertion
