# Late-buyer demo script (two minutes)

Setup, once: `uv run python -m hermes.ledger.seed` (resets DATABASE_URL and loads the synthetic set: 3 suppliers, 4 buyers, 30 invoices; the story invoice is the first late-buyer one, S1/26-27/0010, so the figures below differ from the old hand-seeded Rs 1000000.00 invoice; log in as supplier@kaveri.example to approve),
`HERMES_ENV=development uv run uvicorn hermes.api:app`, `cd web && npm run dev`, open :3000.
Replay any time by running the seed command again. `uv run python -m hermes.demo` plays the whole
story from a fresh reset without the browser; its output is stored in `walkthrough.txt`.

1. (0:00) The page shows one verified invoice, Rs 1000000.00, due 2026-09-15, with the evidence
   score and deadline working. Say: every figure is the API's; the browser does no arithmetic.
2. (0:20) Record the lender advance: `POST /v1/invoices/{id}/advances` as ops with principal
   700000.00. State becomes advanced.
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
