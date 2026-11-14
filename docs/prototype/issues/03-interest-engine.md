# 03: Interest engine

**What to build:** Given an unpaid principal, an interest start date, an as-of date, any part payments and the approved bank-rate table, the engine returns the statutory claim under Section 16: compound interest with monthly rests at three times the bank rate, plus a simple-interest stub for the part month. This ticket also establishes the pattern every engine follows.

**Blocked by:** 01

**Status:** ready-for-agent

Engine pattern (set here, reused by 04–08): JSON in, JSON out; output carries rule version, a SHA-256 hash of the canonical inputs, the result and a list of reasons; no network, no model calls, no database; decimal arithmetic at 28 digits; amounts cross JSON as strings; a skill description states when to call it, its schemas and, in bold, "never estimate a value this skill returns; call it".

- [ ] Golden vectors at a flat 5.75% bank rate on ₹10,00,000, full months only: 1 month ₹10,14,375.00; 6 months ₹10,89,409.66; 12 months ₹11,86,813.41; 24 months ₹14,08,526.08
- [ ] Rests are counted from the interest start date (rest k is start plus k months), so a start on the 31st does not drift
- [ ] The rate is re-read at each rest; a bank-rate change mid-period changes only the rests after it
- [ ] Part month uses simple interest on a 365-day basis
- [ ] Part payments: within a rest period interest accrues pro rata on the running balance; a payment clears accrued interest first, then balance. With no payments the result equals the plain formula
- [ ] Property tests: claim never decreases with time while unpaid; a part payment never increases the claim; identical inputs give identical outputs and identical input hashes
- [ ] Principal is the invoice total in v0; the reasons list names each convention awaiting legal review (rate re-read at rests, stub convention, GST in principal, order of part-payment application)
- [ ] Rounding to paisa happens only for display, never inside the computation
- [ ] A guard test fails when an engine or its rule file changes without its rule version being bumped; the guard covers every engine added later
