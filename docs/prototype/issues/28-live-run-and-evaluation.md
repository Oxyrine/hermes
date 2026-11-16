# 28: Live run and evaluation

**What to build:** The Gemini agent loop gains the model-reading tools, the scenarios can be run for real against the free-tier models, and a small evaluation report says how well the reading tasks perform. All of it is run by hand and reads through the cache, so it costs quota once.

**Blocked by:** 19, 20, 22

**Status:** ready-for-agent

- [x] The loop's allowlist gains the four model-reading tools: classify document, extract fields, detect objection, read contract terms
- [x] A marked, manually invoked run executes the built scenarios with the Gemini loop and real extraction; it is excluded from CI
- [x] Live scenario runs end in the same states as the scripted runs; any difference in figures is a failure
- [x] Evaluation runner reports: extraction exact-match on amounts, dates and GSTINs over the synthetic set after the checks; classification accuracy; objection recall and precision on the 20 threads; drafting (zero stray digits, zero banned phrases)
- [ ] Injection samples: zero planted instructions followed, zero tool calls outside the allowlist
- [x] A second run of either the live scenarios or the evaluation makes zero API calls, and the cache hit count is printed
- [x] The run paces itself within the pinned models' per-minute limits
- [x] The synthetic-only guard is active throughout
- [x] Results are committed as a dated report naming the models and prompt versions used

Note (2026-11-16): injection item left open (loop half not re-verified, Flash-Lite daily quota ran out); the live run used Flash-Lite in place of Flash; second-run-zero-calls is met by the evaluation only. See docs/prototype/reports/live-eval-2026-11-16.md.
