# 06: Evidence score engine

**What to build:** Given the evidence signals found for an invoice and an as-of date, the engine returns a 0–100 score of how strongly the record shows the buyer received and acknowledged the supply, a band, any hard flags, and each signal's contribution with its source. Follows the engine pattern from ticket 03's description. Weights live in a versioned weights file.

**Blocked by:** 01

**Status:** resolved

- [ ] Weights (v0): IRN valid and matching +15; e-way bill matches +10; GRN matches quantity and value +15; PO matches price and quantity +10; IMS explicitly accepted +25; IMS no action, deemed accepted +12; IMS pending 0; buyer email acknowledging receipt +10; part payment received +5; IMS rejected −30 and hard flag; written objection within 15 days −20 and hard flag; debit note −15
- [ ] Deemed acceptance: an IMS "no action" record scores +12 only when the buyer's GSTR-2B generation date for that period is on or before the as-of date; before that date it scores as pending (0). Tests cover the day before, the day of and the day after
- [ ] Score is clamped to 0–100
- [ ] Bands: A at 80 and above, B 60–79, C 40–59, D below 40
- [ ] Any hard flag is returned and forces a "needs review" indication whatever the score
- [ ] Output lists every signal's points and source reference, so the score can be explained line by line
- [ ] Output carries rule version and inputs hash; skill description present; covered by the rule-version guard
