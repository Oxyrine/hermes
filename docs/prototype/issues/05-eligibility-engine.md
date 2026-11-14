# 05: Eligibility engine

**What to build:** Given a supplier's Udyam registration, registration date, enterprise type, classification for the contract's financial year, the contract date and the supply date, the engine says whether the MSMED delayed-payment protections can apply. Follows the engine pattern from ticket 03's description. Rule values live in a versioned rule file.

**Blocked by:** 01

**Status:** resolved

Rules are applied in this order; the first that matches decides.

- [ ] No Udyam registration: `ineligible` (evidence financing only)
- [ ] Classified `medium` in the contract's financial year: `ineligible`
- [ ] Enterprise type `trading`: `manual_review`, reason marked as awaiting legal review
- [ ] Registered on or before the contract date: `eligible`
- [ ] Registered after the contract date: `eligible_at_risk`, reason cites the Silpi Industries position and the NBCC (2025) reference to a larger bench
- [ ] Output includes status, reasons and the classification used
- [ ] Output carries rule version and inputs hash; skill description present; covered by the rule-version guard
