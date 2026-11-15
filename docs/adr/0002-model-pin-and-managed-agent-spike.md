# 0002: Model pin and managed-agent spike (ticket 02)

Status: accepted. Run on 2026-11-15 with the owner's free-tier key. The key is never recorded here.

## Models pinned (`src/hermes/models.toml`)

- Flash: `gemini-3.8-flash` (latest Flash on the AI Studio models page; free of charge on the Standard tier per the pricing page).
- Flash-Lite: `gemini-3.5-flash-lite` (latest Flash-Lite; free of charge on the Standard tier).
- No Pro model is referenced anywhere in configuration (a test enforces this). The key can also call Pro and preview models; they are deliberately unused.
- Limits: Google does not publish per-model free-tier RPM/RPD in its docs and returns no rate-limit headers; the numbers are shown per project in AI Studio, so `models.toml` says "see AI Studio" rather than inventing figures.
- Capacity warning seen today: `gemini-3.8-flash` read-timed-out at 100 s on a one-word prompt and `gemini-3.7-flash` returned 503 "high demand". `gemini-3.5-flash-lite` answered in about 1 s. Ticket 17 needs timeouts and a retry, and should decide a Flash fallback if 3.8 stays slow.

## Managed-agent spike: works, with a caveat

Setup (REST, `v1beta`, header `x-goog-api-key`):

1. `POST /v1beta/agents` with `id`, `base_agent: "antigravity-preview-09-2026"` (the only supported base), `agent_config: {type: "antigravity", model}`, `system_instruction`, and `base_environment: {type: "remote", sources: [inline .agents/AGENTS.md, inline .agents/skills/<name>/SKILL.md]}`. Returned 200 on this tier and region.
2. `POST /v1beta/interactions` with `agent`, `input`, `environment: "remote"`, `tools: [{"type": "code_execution"}]`. Use `background: true` and poll `GET /v1beta/interactions/{id}`; a synchronous call exceeded 170 s.

Result: agent `hermes-spike-lite` (model `gemini-3.5-flash-lite`, per-invoice instructions, one skill `due-date`) completed. The agent called `view_file` on its skill file and went on to reason from it (tool call made, 16.7k tokens). Agent ids cannot start with `gemini-`/`google-` and are unique per project; a named agent's model cannot be overridden per interaction.

Caveat: an agent created with `gemini-3.8-flash` stayed `in_progress` for over 3 minutes on the same prompt (that model is capacity-starved today), so the pin for the agent's own model is Flash-Lite until 3.8 is reliable. Preview status: schemas may change.

## Demo statement

"Hermes runs one managed agent per invoice on the Gemini API; the same agent design also runs as a Gemini function-calling loop, which stays the default until the managed path is reliable."

Prototype decision: the loop built in the other tickets stays the default path; `managed_agent.enabled = false` in `models.toml`. Ticket 17 may flip it for demo invoices.
