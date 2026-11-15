# 02: Managed-agent spike and model pin

**What to build:** We know, in writing, whether Gemini managed agents work on the owner's tier and region, and which two free-tier models Hermes uses. This decides what the demo may claim about its agent.

**Blocked by:** 01

**Status:** resolved

Needs the owner's Gemini API key. Time-boxed to half a day.

- [x] The models the key can call are listed; the latest free-tier Flash and Flash-Lite are pinned in configuration, each with its per-minute and daily limits noted
- [x] No paid-only model (including any Pro model) is referenced anywhere in configuration
- [x] Managed-agent attempt made following the two Google references in the product spec (§14): one agent created with the per-invoice agent instructions and one skill, one tool call made
- [x] Outcome recorded in the decisions record as one of: works (with the setup steps), or does not work (with the exact error, tier or region limit)
- [x] The spike stops at half a day whatever the outcome
- [x] A one-sentence statement for the demo is written to match the outcome (docs/adr/0002)
