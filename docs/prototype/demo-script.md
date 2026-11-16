# Late-buyer demo script (two minutes)

Say about the agent (ticket 02, ADR 0002): "Hermes runs one managed agent per invoice on the Gemini API; the same agent design also runs as a Gemini function-calling loop, which stays the default until the managed path is reliable." The demo itself runs the scripted agent: zero model calls, no API key needed.

Setup, once: `uv run python -m hermes.ledger.seed` (resets DATABASE_URL and loads the synthetic set: 3 suppliers, 4 buyers, 30 invoices; the story invoice is the first late-buyer one, S1/26-27/0010, figures below are the recorded run in `walkthrough.txt`; log in as supplier@kaveri.example to approve),
`HERMES_ENV=development uv run uvicorn hermes.api:app`, `cd web && npm run dev`, open :3000.
Replay any time by running the seed command again. `uv run python -m hermes.demo` plays the whole
story from a fresh reset without the browser; its output is stored in `walkthrough.txt`.

1. (0:00) The page shows the story invoice, Rs 314890.08, with the evidence
   score and deadline working. Say: every figure is the API's; the browser does no arithmetic.
2. (0:20) Record the lender advance: `POST /v1/invoices/{id}/advances` as ops with principal
   220423.06. State becomes advanced.
3. (0:40) Move time: `PUT /dev/clock {"date":"2026-11-14"}`, `POST /dev/tick {}`, then run
   `uv run python -m hermes.dispatcher`. The agent re-runs interest and collateral, marks the
   invoice overdue and proposes a settlement offer. Reload: the chart shows claim value above exposure.
4. (1:00) Approval list: read the draft letter and the engine runs it cites; press Approve as the supplier (the
   named approver and time are recorded). The invoice is settlement offered. Reject would leave it overdue.
5. (1:20) Buyer pays: `POST /dev/payments` as ops with the offer amount, then run the dispatcher.
   The invoice is paid and the page shows the waterfall: lender exposure first, the rest, all
   statutory interest, to the supplier.
6. (1:45) Lender confirms: `POST /v1/invoices/{id}/lender-confirm` as ops. The advance is marked
   repaid and the invoice closes.
