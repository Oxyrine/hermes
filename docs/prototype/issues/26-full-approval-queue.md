# 26: Full approval queue

**What to build:** The bare approval list becomes the real queue: one list across roles, sorted by deadline, where each item shows what it relies on and can be approved, edited or rejected, with a full record of what a person did.

**Blocked by:** 13

**Status:** ready-for-agent

- [ ] One list across roles, sorted by deadline; each user sees only the items their role may act on
- [ ] Each item shows the draft, the engine runs it cites and the documents it relies on
- [ ] Approve, Edit and Reject are available; a destructive choice asks for confirmation in place
- [ ] An edit is stored as a difference against the draft
- [ ] A rejection requires a reason
- [ ] An approved item records who, when and what changed
- [ ] Approvals are bound to a named user; the agent role cannot approve
- [ ] All gates from the product spec (§7) route here with the right approver: low-confidence document link (supplier or operations), objection (operations and supplier), contract terms (operations), settlement offer (supplier, plus lender below the floor), dispute pack release (supplier)
- [ ] An item needing two approvers shows who has approved and who is outstanding
- [ ] Approval publishes an action-approved event
- [ ] Tests through the API cover edit-then-approve, reject without a reason refused, wrong role refused, and a two-approver item
