---
name: statutory-interest
description: Computes the Section 16 (MSMED Act) statutory interest claim on an unpaid invoice. Call it whenever a claim value, interest figure or amount recoverable from a buyer is needed, for any as-of date.
---

# Statutory interest (engine `interest`)

Compound interest with monthly rests at three times the approved bank rate, plus simple interest (365-day basis) for the part month. Rests are counted from the interest start date; the bank rate is re-read at each rest. Part payments clear accrued interest first, then balance.

**Never estimate a value this skill returns; call it.**

No network, no model, no database. Same inputs always give the same output and the same `input_hash`.

## Input (JSON; amounts and rates are strings)

```json
{
  "principal": "1000000",
  "interest_start": "2026-01-31",
  "as_of": "2026-07-15",
  "part_payments": [{"date": "2026-03-10", "amount": "50000"}],
  "bank_rates": [{"effective_from": "2025-01-01", "rate_percent": "5.75"}]
}
```

- `principal`: invoice total in v0 (GST included).
- `bank_rates`: approved rows only; at least one in force on the interest start date.
- `part_payments`: optional; none after `as_of`, none exceeding what is owed.

## Output

```json
{
  "engine": "interest",
  "rule_version": "1.0.0",
  "input_hash": "<sha256 of canonical inputs>",
  "result": {"claim": "<full precision>", "claim_display": "<paisa>", "full_rests": 5},
  "reasons": ["conventions awaiting legal review, one per entry"]
}
```

Show `claim_display` to people; use `claim` for any further computation. Always surface `reasons`.
