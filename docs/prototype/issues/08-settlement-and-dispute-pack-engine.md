# 08: Settlement and dispute-pack engine

**What to build:** Given the engine outputs for an overdue invoice, the engine produces the settlement floor and offer bounds, the data for a neutral buyer statement, and a dispute pack a person can file, as JSON and PDF. Follows the engine pattern from ticket 03's description. It never sends or submits anything.

**Blocked by:** 07

**Status:** ready-for-agent

- [ ] Settlement floor equals lender exposure at the settlement date plus agreed costs
- [ ] Offer equals principal plus statutory interest, less a supplier-chosen discount
- [ ] An offer below the floor is returned with a "needs lender consent" marker rather than refused or silently allowed
- [ ] Buyer statement data: invoice, acceptance date, due date, days late, interest to date, and two neutral notes (a late payment to a micro or small supplier defers the buyer's tax deduction; challenging an award needs a 75% pre-deposit)
- [ ] Settlement letter template uses named placeholders only; every number is filled from engine output
- [ ] Dispute pack JSON contains a document index, a chronology, a claim computation sheet citing each engine run's rule version, and an evidence table with sources
- [ ] Dispute pack PDF renders the same content; every number in the PDF appears in the JSON
- [ ] For an invoice whose eligibility is `ineligible`, no statutory interest figure is produced
- [ ] Output carries rule version and inputs hash; skill description present; covered by the rule-version guard
