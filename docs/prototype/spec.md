# Hermes prototype

Status: ready-for-agent

Source documents: `hermes/Hermes — Implementation Spec.md` (the full product spec, referred to below as "the product spec" with section numbers) and the approved build plan. This spec covers the prototype column of the product spec only.

## Problem Statement

A micro or small supplier in India who has delivered goods to a large buyer often waits months to be paid. The law gives that supplier a strong claim: payment within 15 days (or an agreed term of at most 45), and compound interest at three times the RBI bank rate after that. In practice the supplier cannot turn the claim into cash, because no lender can see whether the invoice is real, whether the buyer accepted the supply, what the claim is worth today, or how it would be recovered.

A lender looking at the same invoice has the mirror problem. The evidence is scattered across GST records, e-invoices, purchase orders, goods receipt notes, emails and bank statements. The statutory claim grows every month, but nobody computes it consistently. And a lender will not rely on numbers produced by a language model.

Today there is nothing to show either party. The Hermes product spec exists, but no software does.

## Solution

Hermes is the evidence, pricing and servicing layer between the supplier and a regulated lender. For each invoice it gathers the records, scores how strongly they show the buyer received and accepted the supply, computes the legal due date and the statutory claim, values the claim against the lender's exposure day by day, and drives the invoice toward settlement or a dispute filing that a person submits.

The prototype demonstrates this on synthetic data, running on a laptop, with three rules that never bend:

- Language models read documents; deterministic, versioned code computes every date and every rupee; a named person approves anything that leaves the system.
- Every figure on screen opens the document quote or the rule version and inputs that produced it.
- Hermes never lends, never takes the receivable, never shares in the statutory interest, and never files anything by itself.

The first thing built after the engines is a thin end-to-end demo of the "late buyer" story: a lender advances against a verified invoice, the due date passes, interest accrues on a chart, a settlement offer is proposed and approved, the buyer pays, the money is split, and the invoice closes. Everything else widens around that working demo.

## User Stories

### Lender

1. As a lender credit officer, I want a portfolio table of every invoice in my tenant with supplier, buyer, total, state, evidence band, days late, claim value, exposure, loan-to-value and alerts, so that I can see my book at a glance.
2. As a lender credit officer, I want to filter the portfolio by state, band and buyer, so that I can focus on the invoices that need attention.
3. As a lender credit officer, I want to export the portfolio as CSV, so that I can use it in my own reporting.
4. As a lender credit officer, I want an invoice detail page with a timeline of every event, engine run and action in order, so that I can reconstruct what happened.
5. As a lender credit officer, I want to see each evidence signal, the points it contributed and its source, so that I understand why an invoice has its score rather than just the number.
6. As a lender credit officer, I want to see the deadline working (acceptance date, basis, payment term used, due date, interest start), so that I can check the legal dates myself.
7. As a lender credit officer, I want a line chart of claim value against my exposure over time, so that I can see whether my cushion is growing or eroding.
8. As a lender credit officer, I want to click any figure and land on the document page and quote, or the rule version and inputs, behind it, so that I never have to trust an unexplained number.
9. As a lender credit officer, I want the evidence band to map to an advance rate set by my policy, so that the offer follows my risk appetite.
10. As a lender credit officer, I want to record a disbursement against a financeable invoice, so that Hermes tracks my exposure without ever moving money itself.
11. As a lender credit officer, I want an alert when loan-to-value exceeds the band limit by five points, so that I can act before the cushion is gone.
12. As a lender credit officer, I want an alert when my nominal rate is above three times the bank rate, so that I know the cushion shrinks with time on that facility.
13. As a lender credit officer, I want a hard flag when a buyer rejects in IMS, raises a written objection or issues a debit note on a funded invoice, so that I learn of a deterioration immediately.
14. As a lender credit officer, I want a settlement that would fall below my exposure plus agreed costs to need my consent, so that the supplier cannot settle away my security.
15. As a lender credit officer, I want a buyer view showing all invoices to one buyer across my suppliers, with the share accepted in IMS and the average days late, so that I can judge the buyer.
16. As a lender credit officer, I want to put a buyer on a watchlist, so that new invoices to that buyer are treated with caution.
17. As a lender credit officer, I want invoices from a supplier registered after the contract date marked as eligible but at risk, so that my policy can decide whether to finance them.
18. As a lender credit officer, I want medium enterprises and unregistered suppliers handled as evidence-only with no statutory interest shown, so that I am not shown a claim that does not exist.
19. As a lender credit officer, I want to see the split of a buyer's payment between my exposure and the supplier, so that I can confirm the invoice can close.
20. As a lender systems owner, I want signed webhook notifications for state changes, hard flags, loan-to-value breaches and items awaiting my consent, so that my own systems can react. (Cut-list item 1.)
21. As a lender systems owner, I want to see only my own tenant's data, so that another lender's book is never exposed to me.

### Supplier

22. As a supplier, I want to see each invoice with a plain-language status such as "Buyer has accepted this in GST" or "Overdue 24 days", so that I understand where I stand without legal vocabulary. (Cut-list item 3.)
23. As a supplier, I want to upload a purchase order, goods receipt note, challan or contract against an invoice, so that my evidence improves.
24. As a supplier, I want to record consent per data source and purpose before Hermes pulls anything, so that I control what is read.
25. As a supplier, I want to see the advance a lender offers and its cost before I accept, so that I can decide with full information. (Cut-list item 3.)
26. As a supplier, I want to approve a settlement offer before it goes to my buyer, so that nothing is sent in my name without my say.
27. As a supplier, I want to choose a discount on the statutory interest in a settlement offer, so that I can trade interest for faster payment.
28. As a supplier, I want to keep all statutory interest that is recovered beyond the lender's exposure and agreed costs, so that the claim stays mine.
29. As a supplier, I want a step-by-step correction draft when my invoice is blocked in GST because it was filed in the wrong table, so that I can hand it to my accountant. (Cut-list item 4.)
30. As a supplier, I want to approve the release of a dispute pack before anyone files it, so that escalation is my decision.
31. As a supplier, I want explanations to cite the rule and suggest an accountant or lawyer for decisions, so that I am informed without being given legal advice.

### Approver and operations

32. As an approver, I want one queue of proposed actions sorted by deadline, so that I handle the most urgent first.
33. As an approver, I want each item to show the draft, the engine runs and the documents it relies on, so that I can check it before approving.
34. As an approver, I want to approve, edit or reject an item, so that I stay in control of the outcome.
35. As an approver, I want my edits stored as a difference against the draft, so that there is a record of what a person changed.
36. As an approver, I want a rejection to carry my reason, so that the next person understands why.
37. As an approver, I want every approval recorded with who, when and what changed, so that approvals are attributable to a named person.
38. As an operations user, I want to confirm a detected objection and its date before it moves any deadline, so that a model's reading never changes a legal date alone.
39. As an operations user, I want to confirm contract payment terms read from a contract, with the clause quote and page in front of me, so that the term used is one a person checked.
40. As an operations user, I want to confirm or refuse a low-confidence link between a document and an invoice, so that fuzzy matches never link automatically.
41. As an operations user, I want to resolve an invoice in manual review and return it to verified, so that review is not a dead end.
42. As an operations user, I want to enter a bank-rate change with its effective date and source, so that the interest engine has the current rate.
43. As a second operations user, I want to approve a bank-rate change someone else entered, and be blocked from approving my own, so that a single mistake cannot change every claim.
44. As an operations user, I want a bank-rate change to recompute interest and collateral on every overdue invoice, so that values stay current.
45. As an operations user, I want an append-only audit log of every write with before and after values, so that any change can be traced.
46. As an operations user, I want to enter the case number after a person files a dispute, so that the invoice state reflects the filing.

### Buyer

47. As a buyer, I want a read-only statement page on a signed link that expires, showing the invoice, delivery evidence, acceptance and due dates and interest to date, so that I can verify the supplier's position. (Cut-list item 2.)
48. As a buyer, I want the statement worded neutrally with no threats or legal conclusions, so that I am informed rather than pressured.

### Evidence and computation

49. As a lender, I want eligibility decided by fixed rules on Udyam registration, classification, enterprise type and registration date against contract date, so that the same facts always give the same answer.
50. As a lender, I want trader registrations sent to manual review, so that an open legal question is not silently decided.
51. As a lender, I want the due date computed from the acceptance date with a 15-day default and a 45-day cap on any agreed term, so that the statutory deadline is applied exactly.
52. As a lender, I want a written objection raised within 15 days of delivery to move the acceptance date to the day it was removed, and one raised later to be ignored, so that the deadline follows the statute.
53. As a lender, I want an invoice with an unremoved objection to show that acceptance is not yet fixed, so that no due date is invented.
54. As a lender, I want statutory interest compounded with monthly rests at three times the bank rate, with a simple-interest stub for the part month, so that the claim matches the statute.
55. As a lender, I want a bank-rate change mid-period to affect only the rests after it, so that history is not rewritten.
56. As a lender, I want a part payment applied to interest first and then principal, never increasing the claim, so that receipts are treated consistently.
57. As a lender, I want an IMS "no action" record to count as deemed accepted only from the date the buyer's GSTR-2B for that period is generated, so that deemed acceptance is not credited early.
58. As a lender, I want the evidence score clamped to 0–100 with bands A to D and any hard flag forcing review whatever the score, so that a high score cannot hide a rejection.
59. As a lender, I want every computed result to carry its rule version and a hash of its inputs, so that any figure can be recomputed and compared.
60. As a lender, I want rules awaiting legal sign-off clearly marked, so that I know which conventions are provisional.
61. As a lender, I want extracted document fields accepted only when the model's quote appears in the document text, the arithmetic adds up and the GSTIN checksum is valid, so that a misread document cannot enter the ledger.
62. As a lender, I want extracted values that disagree with the GST or e-invoice record recorded as evidence of a mismatch rather than resolved by the model, so that discrepancies stay visible.
63. As a lender, I want instructions planted inside documents or emails ignored, so that a hostile document cannot steer the system.
64. As a lender, I want drafted letters to contain no digit that is not in the engine output and no banned phrase, so that prose can never carry an invented number or a threat.
65. As a lender, I want the dispute pack to contain a document index, chronology, claim computation sheet with rule versions and an evidence table with sources, as PDF and JSON, so that a person can file it.
66. As a lender, I want no code path that submits to the dispute portal, so that filing is always a human act.

### Agent and events

67. As an operations user, I want each invoice maintained by one agent that reacts to events (new document, IMS change, payment, deadline passed, bank-rate change, approval), so that work happens when something changes.
68. As an operations user, I want the agent limited to twelve tool calls per event and to an allowlist of tools that cannot send anything outside Hermes, so that it cannot run away or leak.
69. As an operations user, I want the agent to stop and propose a review whenever a skill returns manual review, a hard flag or low confidence, so that uncertainty reaches a person.
70. As an operations user, I want only one agent run per invoice at a time, so that concurrent events cannot corrupt an invoice.
71. As an operations user, I want a failing event retried and set aside after five attempts, so that one bad event does not block the queue.
72. As an operations user, I want each agent run recorded with tokens, tool calls and duration, so that cost and behaviour are visible.
73. As an operations user, I want an invoice whose model quota is exhausted routed to review rather than failing, so that free-tier limits degrade service gracefully.

### Builder and presenter

74. As the builder, I want model responses cached by document hash, so that re-seeding, re-running scenarios and rehearsing the demo spend no free-tier quota.
75. As the builder, I want the whole test suite to pass with no API key and no network, so that CI is free and deterministic.
76. As the builder, I want live-model scenario runs and evaluations to be a deliberate manual step, so that quota is spent only when a prompt or model changes.
77. As the builder, I want to move the system clock in the development environment, so that "the due date passes" can be tested and demonstrated in seconds.
78. As the builder, I want a change to any engine or its rule file to fail the build unless the rule version was bumped, so that versions always mean something.
79. As the builder, I want a synthetic data set of 3 suppliers, 4 buyers and 30 invoices with documents, emails, bank statements and GST fixtures, each with ground truth, so that every scenario has data and extraction can be scored.
80. As the builder, I want every data source behind one adapter interface, so that fixtures can later be swapped for live APIs without touching the engines.
81. As the presenter, I want a seed-and-reset command and a two-minute script for the late-buyer story, so that the demo can be run from clean at any time.
82. As the presenter, I want the demo to work from the end of the second build phase onward, so that there is always something to show if a submission date appears.
83. As the presenter, I want an honest statement of whether the demo runs on managed agents or on the function-calling loop, so that the submission's claims match what is shown.

## Implementation Decisions

### Shape of the system

- Local-first. PostgreSQL in Docker, local file storage and a database-backed event queue stand in for Cloud SQL, Cloud Storage and Pub/Sub. Each sits behind the interface the product spec names, so the cloud versions are a later swap.
- One Python project for engines, API, adapters, agent and synthetic data; one Next.js application for all front ends. Plain SQL, no ORM and no migration tool in the prototype: the schema is the product spec's DDL plus the additions listed below.
- A single write path. Front ends, the agent and adapters all write through the HTTP API. The agent has no database access.
- Hermes gets its own private repository. Commits carry the owner's identity only.

### Modules

- **Six engines** (eligibility, deadline, interest, evidence score, collateral, settlement and dispute pack). Each is a deep module with one narrow interface: JSON in, JSON out, returning rule version, inputs hash, result and reasons. No network, no model calls, no database. Rule values live in versioned data files beside the engine. Each carries a skill description stating when to call it, its schemas and the rule "never estimate a value this skill returns; call it".
- **Ledger and API.** Owns the schema, tenancy, authentication, audit log, idempotency and the engine-run endpoint.
- **State machine.** One module holds the transition table and guards and is the only code that changes an invoice's state. It emits the state-changed event.
- **Adapters.** One fetch interface per source returning raw records; raw payloads stored unchanged; each ingest publishes an event. Prototype adapters read fixtures.
- **Matching.** Links an external record to an invoice on GSTINs, invoice number, date and amount. Exact matches link; fuzzy matches below threshold create a review action and never link.
- **Model client.** The only place a model is called. Enforces structured output, temperature zero for extraction and detection, documents passed as files, one retry then review, the response cache, and the seven output checks from the product spec (§6).
- **Dispatcher and agent runner.** The dispatcher claims an event, takes a per-invoice lock, runs the agent and records the run. The agent runner has three implementations behind one interface: scripted (the event-to-skills table as code), a Gemini function-calling loop, and managed agents if the early spike succeeds.
- **Actions and artefacts.** Approval queue, settlement offer, dispute pack, correction draft, buyer statement, webhooks.
- **Synthetic data generator.** Produces documents with ground truth, email threads, bank statements and GST fixtures.

### Decisions that depart from or complete the product spec

- **Models.** Free-tier only. Two models are pinned in configuration after checking the live list: the latest free Flash for contract terms, objection detection, mismatch notes, drafting and agent reasoning; Flash-Lite for classification and extraction, escalating to Flash on low confidence. No Pro model. Contract terms remain human-confirmed.
- **Response cache.** Keyed by task, model, prompt version and document hash. A hit never calls the API. A rate-limit error backs off; an exhausted daily limit routes the item to review.
- **Agent.** The function-calling loop is built first. A half-day spike at the start tests managed agents; the result decides whether demo invoices switch at the end.
- **Schema additions.** Tables for agent runs, consents, users and roles, webhook subscriptions and deliveries, raw records, idempotency keys, the event queue and the model cache. A tenant id on every tenant-scoped table (buyers and bank rates stay global). Documents may be unlinked or supplier-level. Action requests gain expiry, reject reason, edit difference and lender-consent fields. Invoices gain an agent session reference and a stored due date.
- **Tenancy.** Every query filters by tenant from the start. Database row-level security is layered on later and is a cut-list item.
- **State machine additions.** Manual review can return to verified once a person resolves it. Financeable can move to overdue.
- **Interest with part payments.** Monthly rests stay anchored to the interest start date, counted from that date so month-end dates do not drift. Within a rest period interest accrues pro rata on the running balance; a payment clears accrued interest first, then balance. With no payments this equals the product spec's formula. Marked for legal review.
- **Deemed acceptance.** An IMS "no action" record scores as deemed accepted only when the buyer's GSTR-2B generation date for that period is on or before the as-of date; before that it scores as pending. Fixtures carry the generation date per record.
- **Waterfall.** Receipts cover the lender's exposure and agreed costs first; the remainder, including all statutory interest, goes to the supplier. There is no interest-linked fee.
- **Clock.** Time is injected. A development-only endpoint sets it, and a tick operation emits deadline-passed and offer-expired events and writes the day's collateral snapshots.
- **Money.** Decimal arithmetic at 28 digits inside engines; amounts cross JSON as strings and are rounded to paisa only at the API boundary. The front end performs no money arithmetic.
- **Bank rates.** Seeded from RBI releases looked up at build time, not from memory. A database constraint requires the approver to differ from the person who entered the rate. The interest engine receives approved rows only.
- **Authentication.** Signed tokens carrying tenant and role, issued by a development login that picks a seeded user. Roles: lender operations, lender approver, supplier, Hermes operations, agent. Identity Platform and MFA are pilot work.
- **Document text.** The quote check uses the PDF text layer. Scans and photographs are outside the prototype.
- **Legal guardrails as structure.** No data model for assignment of receivables, no code path that submits to a portal, no tool the agent can use to send anything outside Hermes.

### API contract

The fourteen endpoints of the product spec (§8) are the contract, with the invoice read returning state, eligibility, deadline, claim, evidence and collateral in the shape shown there, plus the collateral series for the chart. Development-only additions: login, clock, and a payment entry used by the slice.

### Build order

1. Setup, managed-agent spike, model check.
2. Engines.
3. Vertical slice: the late-buyer story end to end with a minimal API, the scripted runner, hand-seeded data, one invoice page with the chart and a bare approval list. Demo script and reset command written here.
4. Ledger and API widened.
5. Synthetic data and adapters.
6. Model layer.
7. Agent on Gemini.
8. Remaining actions and the dispute pack.
9. All six scenarios.
10. Front end widened.
11. Cut-list items.
12. Checklists, rehearsal, deploy.

### Cut list

Never cut: the six engines with golden tests, the late-buyer path, the human approval gate.

If time runs short, cut in this order: webhooks; buyer statement page; supplier app; GSTR-1A correction draft; row-level security. They are built last, in reverse of this order, and nothing in the never-cut set depends on them.

## Testing Decisions

A good test here checks behaviour a lender, supplier or approver could observe: a figure, a state, a proposed action, a refusal. It does not assert which internal function ran or how a table is laid out.

Two seams, and no others:

1. **The engine interface** (JSON in, JSON out). Engines are tested like accounting code, with exact expected outputs.
   - Golden vectors: the four interest values in the product spec; deadline cases (no agreement, agreed 30, agreed 60 capped at 45, objection on day 10 removed on day 25, objection on day 20 ignored, open objection); eligibility cases (registered before and after the contract, medium, trader, none); deemed acceptance either side of the GSTR-2B date.
   - Property tests: claim never decreases with time while unpaid; a part payment never increases the claim; loan-to-value falls over time when the lender rate is below three times the bank rate; identical inputs give identical outputs.
   - A rate change mid-period changes only the rests after it.
   - A guard test fails when an engine or its rule file changes without a version bump.

2. **The HTTP API plus the clock.** The six scenarios from the product spec (§12) are scripted stories driven only through API calls, fixture ingestion, the tick operation and approval calls, asserting on API responses. They run with the scripted agent runner and a fake model that returns ground truth by document hash, so they need no key. The late-buyer scenario is written first and must keep passing after every later phase.

Also tested through the API seam: tenant isolation (a user from one tenant reads nothing of another), state-machine guards, audit rows on writes, idempotent retries, and the two-person bank-rate rule.

The seven model-output checks are pure functions with unit tests, since each is a small rule with exact inputs and outputs.

Live-model runs are separate and manual: the same scenarios with the Gemini loop and real extraction, and a small evaluation runner reporting extraction accuracy on the synthetic set, objection recall and precision on twenty threads, and a handful of prompt-injection documents. Both read through the cache, and a second run must make zero API calls.

There is no prior art in this codebase; Hermes is greenfield.

## Out of Scope

- Everything in the pilot and production columns of the product spec: licensed GSP access, e-invoice and e-way bill APIs, Account Aggregator, Gmail or Outlook OAuth, TReDS, ERP connectors.
- Google Cloud infrastructure beyond one final deploy of the API, front end and database: Pub/Sub, Eventarc, a service per skill, VPC Service Controls, per-tenant encryption keys, BigQuery export, disaster recovery. The final deploy itself is blocked until a billing-enabled project exists.
- Paid Gemini models.
- Identity Platform, MFA and single sign-on.
- Hindi and Tamil.
- OCR of scans and photographs.
- The full-size evaluation sets (300 documents, 200 threads, 50 injection documents) and the pilot metrics.
- Legal sign-off on the rules marked for legal review or counsel; the prototype ships rule set v0 with those marks intact.
- Lending, holding funds, taking assignment of receivables, filing on the dispute portal, and legal advice. These are out of scope for the product, not only the prototype.

## Further Notes

- The managed-agent spike is capped at half a day. Whatever it finds is written down, and the demo's description of the agent follows from it.
- The product spec's example invoice response contains an interest figure it labels illustrative; it is not a test vector.
- Rules marked for legal review in the product spec (day-count convention, rate re-read at each rest, stub convention, GST in principal, order of part-payment application, trader registrations) keep that mark in rule files and in output reasons.
- The owner's standing security, launch and polish checklists are worked through in the last phase and reported item by item. Known outcomes: no cookie banner (no tracking), no marketing pages.
