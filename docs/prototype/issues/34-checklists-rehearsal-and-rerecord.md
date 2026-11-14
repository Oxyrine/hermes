# 34: Checklists, rehearsal and re-record

**What to build:** The prototype is audited against the owner's three standing checklists, the demo is rehearsed from clean and recorded again, and the demo's description of its agent is made true.

**Blocked by:** 25, 26, 27

**Status:** ready-for-agent

- [ ] Security checklist (20 items) worked through against the code and reported per item as done, already fine, or deliberately skipped with the reason
- [ ] Launch checklist (20 items) reported the same way. Known outcomes: no cookie banner because there is no tracking; no marketing pages
- [ ] Polish checklist (20 items) reported the same way, judging each item's applicability to an application rather than a content site
- [ ] Engineering items found missing are implemented; items needing real content or a decision are reported, not invented
- [ ] Dependencies are scanned and findings addressed or recorded
- [ ] The demo runs from the seed-and-reset command with a warm cache and makes zero model calls
- [ ] If ticket 02 found managed agents working, the demo invoices run on them; if not, the demo script carries the honest one-sentence statement from ticket 02
- [ ] The demo walkthrough is recorded again on the finished system, replacing the recording from ticket 12
- [ ] The readme explains what Hermes is, how to run it, how to run the demo, and what is deliberately not in the prototype
- [ ] All built scenarios pass
