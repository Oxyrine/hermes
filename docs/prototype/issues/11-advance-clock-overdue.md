# 11: Advance, clock, overdue

**What to build:** The lender records an advance on the seeded invoice. The presenter moves the clock past the due date. The invoice becomes overdue by itself, interest starts to accrue, and the invoice page shows claim value against exposure as a line chart.

**Blocked by:** 10

**Status:** ready-for-agent

- [ ] A state machine holds the full transition table and guards from the product spec (§4), plus manual review to verified and financeable to overdue; it is the only code that changes an invoice's state, and it refuses any transition not in the table
- [ ] Verified to financeable requires band A–C and eligibility other than `ineligible`
- [ ] Recording an advance creates the advance row and moves financeable to advanced; Hermes moves no money
- [ ] Time is injected; a development-only endpoint sets the clock
- [ ] A tick for a given date emits a deadline-passed event for each unpaid invoice past its stored due date and writes that day's collateral snapshot rows
- [ ] Events sit in a queue; a dispatcher claims one, takes a per-invoice lock so only one run touches an invoice at a time, runs the agent and releases
- [ ] The scripted agent runner implements the product spec's event table (§7): on deadline passed it re-runs interest and collateral through the API and the invoice moves to overdue
- [ ] The agent writes only through the API
- [ ] Invoice timeline lists events, engine runs and state changes in order
- [ ] Invoice page shows claim value and exposure over time as two lines, drawn from API data only
- [ ] A test through the API: advance, set clock past due, tick, drain; asserts state `overdue` and a claim above principal
