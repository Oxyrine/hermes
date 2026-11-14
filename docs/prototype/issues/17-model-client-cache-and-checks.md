# 17: Model client, cache and checks

**What to build:** One internal client through which every model call passes. It enforces structured output, caches responses so free-tier quota is never spent twice on the same document, refuses anything that is not synthetic data, and provides the checks every model output must pass. A fake model lets the whole suite run with no key. No task-specific reading yet; that is ticket 18.

**Blocked by:** 02, 09, 10

**Status:** ready-for-agent

- [ ] No code outside this client calls a model
- [ ] Only the two pinned free-tier models can be selected; a request for any other model is refused
- [ ] Structured output is enforced against a schema; a response that fails validation is retried once, then returned as "route to review"
- [ ] Temperature is zero for extraction and detection tasks; documents are passed as files, never pasted into the system instruction
- [ ] Response cache keyed by task, model, prompt version and document hash; a hit makes no API call; hit and miss counts are reported
- [ ] A rate-limit error backs off and retries; an exhausted daily limit returns "route to review" instead of raising
- [ ] Synthetic-only guard: with `HERMES_DATA_MODE=synthetic` (the default), the client refuses any document whose hash is not in the synthetic manifest, before any network call; the refusal is logged without document content
- [ ] Logs never contain document text or customer data
- [ ] Schema check, as a tested pure function
- [ ] Quote check: every source quote must appear in the document's text layer after whitespace normalisation; a missing quote voids that field
- [ ] Arithmetic check: line items sum to taxable value; taxable value plus GST equals total within ₹1
- [ ] GSTIN checksum check
- [ ] Cross-source check: a disagreement with the GST or e-invoice record is returned as mismatch evidence, never resolved
- [ ] Threshold check: confidence below 0.9 on amounts, dates or GSTINs routes to review
- [ ] Drafting check: no digit in a draft that is absent from the supplied engine output; no phrase from the banned list (threats, legal conclusions)
- [ ] A fake model returns ground truth by document hash, so tests need no key and no network
