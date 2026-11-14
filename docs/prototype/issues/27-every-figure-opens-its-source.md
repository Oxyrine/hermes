# 27: Every figure opens its source

**What to build:** On any screen, clicking a number or date shows where it came from: the document, page and quote it was read from, or the engine, rule version and inputs that computed it.

**Blocked by:** 18, 25

**Status:** ready-for-agent

- [ ] Every extracted value on the invoice page opens its document at the right page with the quote shown
- [ ] Every computed value (due date, interest, claim, exposure, loan-to-value, score) opens its engine run: engine, rule version, inputs and reasons
- [ ] Each evidence contribution opens its source record (IMS event, document, payment)
- [ ] Rules awaiting legal review are marked as provisional where their result is shown
- [ ] The API can recompute an engine run from its stored inputs and report whether the output matches
- [ ] The same behaviour is available from the portfolio, the approval queue and the invoice page
- [ ] The source panel works by keyboard and at phone width
- [ ] A test through the API asserts that every figure in the invoice read response carries a source reference that resolves
