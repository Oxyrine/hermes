# 27: Every figure opens its source

**What to build:** On any screen, clicking a number or date shows where it came from: the document, page and quote it was read from, or the engine, rule version and inputs that computed it.

**Blocked by:** 18, 25

**Status:** resolved

- [x] Every extracted value on the invoice page opens its document at the right page with the quote shown
- [x] Every computed value (due date, interest, claim, exposure, loan-to-value, score) opens its engine run: engine, rule version, inputs and reasons
- [x] Each evidence contribution opens its source record (IMS event, document, payment)
- [x] Rules awaiting legal review are marked as provisional where their result is shown
- [x] The API can recompute an engine run from its stored inputs and report whether the output matches
- [x] The same behaviour is available from the portfolio, the approval queue and the invoice page
- [x] The source panel works by keyboard and at phone width (links and a plain page, no scripts; checked in headless Chromium at 400 px against a stub API: no horizontal overflow, recompute button reachable and operable by keyboard)
- [x] A test through the API asserts that every figure in the invoice read response carries a source reference that resolves
