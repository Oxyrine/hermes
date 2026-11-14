# 19: Scenario 1, clean path

**What to build:** The happy story runs end to end from an upload: invoice, IRN, e-way bill, goods receipt note and IMS acceptance give band A; the lender advances; the buyer pays on time; the invoice closes. Any gaps between the earlier tickets that this story exposes are closed here.

**Blocked by:** 18

**Status:** ready-for-agent

- [ ] Starting from upload and fixture ingestion only, the invoice reaches verified with no manual step
- [ ] Evidence score is 80 or above, band A, with no hard flags
- [ ] The invoice becomes financeable and the advance offered is 80% under policy v0
- [ ] After the advance is recorded and the buyer pays before the due date, the invoice moves to paid; no statutory interest is claimed
- [ ] The waterfall runs and the invoice closes on lender confirmation
- [ ] The scenario passes as a test driven only through the API, fixture ingestion, the clock and approval calls, with the scripted runner and fake model
- [ ] The late-buyer scenario still passes
