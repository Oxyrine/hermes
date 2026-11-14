# 23: Dispute pack and offer expiry

**What to build:** A settlement offer that is not taken up expires. With the supplier's consent a dispute pack is generated, the supplier approves its release, a person files it on the portal, and that person records the case number. Hermes submits nothing. Covers scenario 5.

**Blocked by:** 12

**Status:** ready-for-agent

- [ ] A settlement-offer action carries an expiry; the tick emits an offer-expired event when it passes
- [ ] On expiry or refusal, and with the supplier's consent to escalate, the invoice moves to dispute-ready
- [ ] A dispute-pack action is proposed with the PDF and JSON from the settlement engine attached
- [ ] The pack's computation sheet cites the stored engine runs and their rule versions; every figure equals those runs
- [ ] The supplier approves release; approval records who and when
- [ ] The invoice moves to filed only when a person enters the case number
- [ ] Recording an award requires an uploaded award document
- [ ] There is no code path that contacts the dispute portal
- [ ] The pack can be downloaded from the approval item and the invoice page
- [ ] Scenario 5 passes: offer expires, pack generated, supplier approves, case number entered
