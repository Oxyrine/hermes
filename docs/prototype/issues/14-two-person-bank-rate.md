# 14: Two-person bank rate

**What to build:** An operations user enters a bank-rate change with its effective date and source. A different operations user approves it. Every overdue invoice's interest and collateral then recompute.

**Blocked by:** 12

**Status:** ready-for-agent

- [ ] An entered rate is not used by the interest engine until approved
- [ ] The person who entered a rate cannot approve it; the database also enforces that the two differ
- [ ] The entry records a source link
- [ ] Approval emits a bank-rate-changed event that fans out to every overdue invoice
- [ ] After the fan-out, each overdue invoice has new interest and collateral runs; invoice states do not change
- [ ] A rate effective mid-period changes only the rests after its effective date, visible in the recomputed claim
- [ ] A minimal admin screen lists rates with their status and offers Enter and Approve
- [ ] A test through the API covers enter, self-approval refused, second-person approval and recompute
