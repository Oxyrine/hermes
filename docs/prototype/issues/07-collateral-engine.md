# 07: Collateral engine

**What to build:** Given an invoice's eligibility, deadline, payments, evidence band, any advance and the lender's terms, the engine values the claim, the lender's exposure and the loan-to-value on a given day, raises alerts, and splits receipts between lender and supplier. Follows the engine pattern from ticket 03's description. Lender policy lives in a versioned policy file.

**Blocked by:** 03

**Status:** ready-for-agent

- [ ] Claim value is the statutory claim (from the interest engine) when eligibility is `eligible` and the due date has passed; otherwise the unpaid principal
- [ ] Exposure is the advance compounded monthly at the lender's nominal rate, plus a stub for the part month
- [ ] Loan-to-value is exposure divided by claim value
- [ ] Advance rate by band (policy v0): A 80%, B 70%, C 50%, D 0%
- [ ] Alert when loan-to-value exceeds the band's limit by more than 5 points
- [ ] Alert "cushion erodes with time" when the lender's nominal rate is above three times the bank rate
- [ ] Alert on any hard flag after funding
- [ ] Waterfall: receipts cover the lender's exposure and agreed costs first; the remainder, including all statutory interest, goes to the supplier; there is no interest-linked fee line; the parts sum exactly to the receipts
- [ ] Property test: loan-to-value falls over time whenever the lender rate is below three times the bank rate
- [ ] A series of daily values can be produced for a date range, for the claim-versus-exposure chart
- [ ] Output carries rule version and inputs hash; skill description present; covered by the rule-version guard
