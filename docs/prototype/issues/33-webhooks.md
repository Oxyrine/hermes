# 33: Webhooks

**What to build:** A lender subscribes an endpoint and receives signed notifications when an invoice changes state, a hard flag is raised, loan-to-value is breached or an item awaits their consent. Completes scenario 6.

**Blocked by:** 21

**Status:** ready-for-agent

Cut-list position 1 of 5 (the first to be cut). If cut, scenario 6 is asserted up to the flag only.

- [ ] A lender can subscribe an endpoint to events and receives a signing secret once
- [ ] Four events are sent: invoice state changed, invoice hard flag, collateral loan-to-value breach, action awaiting lender
- [ ] Payloads carry ids only; details are read through the API
- [ ] Each payload is signed with HMAC-SHA256 in the signature header
- [ ] Failed deliveries are retried with exponential backoff for 24 hours; each attempt is recorded
- [ ] Only HTTPS endpoints are accepted outside the development environment; private and loopback addresses are refused outside development
- [ ] A subscription delivers only its own tenant's events
- [ ] Scenario 6 passes in full: after an IMS reversal on a funded invoice, a local receiver gets a correctly signed hard-flag webhook within 5 minutes of the event
