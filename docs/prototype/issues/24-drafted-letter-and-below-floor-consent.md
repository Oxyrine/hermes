# 24: Drafted letter and below-floor consent

**What to build:** The settlement letter gains model-written prose around its placeholders, with every number still filled from engine output. A supplier can choose a discount, and an offer that would fall below the lender's floor cannot go out without the lender's consent.

**Blocked by:** 12, 17

**Status:** ready-for-agent

- [ ] The model writes prose containing placeholders only; numbers are filled by the template from engine output
- [ ] A draft containing a digit not present in the engine output is rejected and the plain template is used instead
- [ ] A draft containing a banned phrase (a threat or a legal conclusion) is rejected and the plain template is used instead
- [ ] The letter states the neutral notes from the buyer statement and nothing stronger
- [ ] The supplier can set a discount on statutory interest; the offer amount is recomputed by the engine, not in the browser
- [ ] An offer below the floor is held, flagged as needing lender consent, and appears in the lender's queue
- [ ] The offer can be approved for sending only after the lender consents; consent records who and when
- [ ] An offer at or above the floor needs only the supplier's approval
- [ ] With no key or an exhausted limit, the plain template is used and the flow still completes
- [ ] Tests through the API cover: clean draft accepted, stray digit rejected, banned phrase rejected, below-floor held then released
