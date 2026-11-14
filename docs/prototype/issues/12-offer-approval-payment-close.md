# 12: Offer, approval, payment, close

**What to build:** For the overdue invoice, a settlement offer is proposed. A person approves it in an approval list. The buyer pays, the receipts are split between lender and supplier, and the invoice closes. This completes the late-buyer story (scenario 3) and leaves a demo that can be run and replayed at any time.

**Blocked by:** 08, 11

**Status:** ready-for-agent

- [ ] When an invoice becomes overdue the scripted runner proposes a settlement-offer action whose draft is the template filled from engine output and which cites the engine runs it relies on
- [ ] Nothing is marked sent without an approved action; approval records the named user and time
- [ ] Approving moves the invoice to settlement offered; rejecting leaves it overdue
- [ ] A bare approval list shows proposed actions with Approve and Reject
- [ ] A development payment entry records a receipt; interest and collateral re-run
- [ ] When receipts cover the amount due the invoice moves to paid; the waterfall runs; on lender confirmation the advance is marked repaid and the invoice closes
- [ ] The invoice page shows the waterfall split
- [ ] The late-buyer scenario passes as a test driven only through the API, the clock and approval calls, with no API key
- [ ] A seed-and-reset command returns the system to the start of the story
- [ ] A two-minute demo script is written and works from a fresh reset
- [ ] A recorded walkthrough of the script is captured and stored with the project
