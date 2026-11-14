# 22: Gemini agent loop

**What to build:** The per-invoice agent can run on Gemini instead of the script. Given an event and the invoice summary, a function-calling loop on the free Flash model decides which skills to run, calls them through the Hermes API, and proposes the next human action. Scoped to engine and API tools; the model-reading tools join in ticket 28.

**Blocked by:** 02, 12

**Status:** ready-for-agent

- [ ] The per-invoice agent instructions from the product spec (§7) are the system instruction, unchanged in substance
- [ ] The runner is chosen by configuration; the scripted runner remains the default for tests and for an offline demo
- [ ] Tools offered: read invoice, run each of the six engines, write an engine result, propose an action. Each is a thin call to the Hermes API with the agent's own token
- [ ] The tool list is an allowlist; a call to anything not on it is refused and recorded
- [ ] No tool can send anything outside Hermes, and the agent has no database access
- [ ] At most 12 tool calls per event; on reaching the cap the loop stops and proposes a review
- [ ] When a skill returns manual review, a hard flag or low confidence, the loop stops and proposes a review
- [ ] Every proposal cites the engine run ids and document ids it relies on
- [ ] Each run is recorded with tokens, tool calls and duration
- [ ] A failing event is retried and set aside after 5 attempts without blocking other invoices
- [ ] An exhausted daily model limit routes the invoice to review rather than failing the event
- [ ] Unit tests drive the loop with a stubbed model: cap reached, disallowed tool, manual-review stop
- [ ] By hand, with a key: the late-buyer story runs on the loop and ends in the same states and figures as the scripted run
