# 04: Deadline engine

**What to build:** Given a delivery or completion date, a written payment term (or none) and a written objection (or none), the engine returns the acceptance date and its basis, the payment due date and the day interest starts, under MSMED Act sections 2 and 15. Follows the engine pattern from ticket 03's description.

**Blocked by:** 01

**Status:** ready-for-agent

- [ ] No written term: due 15 days after acceptance
- [ ] Written term of 30 days: due 30 days after acceptance
- [ ] Written term of 60 days: capped at 45
- [ ] Objection raised on day 10 and removed on day 25: acceptance moves to day 25, basis "objection removed"
- [ ] Objection raised on day 20 (after the 15-day window): ignored, acceptance is the delivery date
- [ ] Objection raised within 15 days and not removed: status "open objection", no due date returned, reason "acceptance not yet fixed"
- [ ] Interest starts the day after the due date
- [ ] Product spec example reproduces: acceptance 2026-08-01 with a 45-day term gives due 2026-09-15 and interest from 2026-09-16
- [ ] Delivery in instalments: v0 uses the last goods-receipt date and flags it in reasons
- [ ] The day-count convention (inclusive or exclusive) is named in reasons as awaiting legal review
- [ ] Output carries rule version and inputs hash; skill description present; covered by the rule-version guard
