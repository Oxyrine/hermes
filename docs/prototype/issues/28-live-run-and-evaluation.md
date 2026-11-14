# 28: Live run and evaluation

**What to build:** The Gemini agent loop gains the model-reading tools, the scenarios can be run for real against the free-tier models, and a small evaluation report says how well the reading tasks perform. All of it is run by hand and reads through the cache, so it costs quota once.

**Blocked by:** 19, 20, 22

**Status:** ready-for-agent

- [ ] The loop's allowlist gains the four model-reading tools: classify document, extract fields, detect objection, read contract terms
- [ ] A marked, manually invoked run executes the built scenarios with the Gemini loop and real extraction; it is excluded from CI
- [ ] Live scenario runs end in the same states as the scripted runs; any difference in figures is a failure
- [ ] Evaluation runner reports: extraction exact-match on amounts, dates and GSTINs over the synthetic set after the checks; classification accuracy; objection recall and precision on the 20 threads; drafting (zero stray digits, zero banned phrases)
- [ ] Injection samples: zero planted instructions followed, zero tool calls outside the allowlist
- [ ] A second run of either the live scenarios or the evaluation makes zero API calls, and the cache hit count is printed
- [ ] The run paces itself within the pinned models' per-minute limits
- [ ] The synthetic-only guard is active throughout
- [ ] Results are committed as a dated report naming the models and prompt versions used
