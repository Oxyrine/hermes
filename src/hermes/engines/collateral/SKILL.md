---
name: collateral
description: Values an invoice claim, the lender's exposure and loan-to-value on a given day (or a daily series), raises collateral alerts, and splits receipts between lender and supplier. Call it whenever a loan-to-value, exposure, claim value or payout split is needed.
---

# Collateral (engine `collateral`)

Claim value is the statutory claim (computed by the `interest` skill, passed in as `statutory_claim`) when eligibility is not `ineligible` and the due date has passed; otherwise the unpaid principal. Exposure is the advance compounded monthly at the lender's nominal rate from `funded_on`, plus simple interest (365-day) for the part month. LTV = exposure / claim. Lender policy (advance rate by band, alert margin) is in `rules.json`.

**Never estimate a value this skill returns; call it.**

## Input (JSON; amounts and rates are strings)

```json
{
  "eligibility": "eligible", "band": "B",
  "principal": "1000000", "payments": [{"date": "2026-03-10", "amount": "50000"}],
  "due_date": "2026-01-31", "as_of": "2026-07-15", "statutory_claim": "1089409.66",
  "advance": "700000", "funded_on": "2026-02-01", "lender_rate_percent": "18",
  "bank_rate_percent": "5.75",
  "hard_flags": [{"date": "2026-04-01", "kind": "ims_rejection"}],
  "receipts": "1200000", "agreed_costs": "5000"
}
```

- `advance`, `funded_on`, `hard_flags`, `payments`, `receipts`, `agreed_costs` are optional.
- Series: replace `as_of`/`statutory_claim` with `"range": {"from": "...", "to": "..."}` and `"statutory_claims": {"<date>": "<claim>"}` for every day in range.

## Output

`result`: `date`, `claim_value`, `exposure`, `ltv` (null when unfunded), `advance_rate`, `alerts` (`ltv_above_band_limit`, `cushion erodes with time`, `hard_flag_after_funding`), and `waterfall` `{lender_exposure, costs, supplier}` when `receipts` is given (parts sum exactly to receipts). A series returns `{"series": [one such object per day]}`. The envelope carries `rule_version`, `input_hash` and `reasons`; always surface `reasons`.
