---
name: payment-deadline
description: Computes the MSMED Act (sections 2 and 15) acceptance date, payment due date and the day statutory interest starts for a supplier invoice. Call it whenever a due date, acceptance date or interest start date is needed; never work these out yourself.
---

# Payment deadline (engine `deadline`)

Acceptance is the delivery date, or the date a written objection raised within 15 days of delivery was removed. An objection raised later is ignored; one raised in time and not removed leaves acceptance unfixed. Due date is acceptance plus the written term (capped at 45 days) or 15 days if none. Interest starts the day after the due date.

**Never estimate a value this skill returns; call it.**

No network, no model, no database. Same inputs always give the same output and the same `input_hash`.

## Input (JSON; dates are ISO strings)

```json
{
  "delivery": "2026-08-01",
  "instalment_dates": ["2026-07-20", "2026-08-01"],
  "written_days": 45,
  "objection": {"raised_on": "2026-08-05", "removed_on": "2026-08-20"}
}
```

- `delivery`: GRN, e-way bill, challan or completion date.
- `instalment_dates`: optional; if present the last date replaces `delivery` (v0) and this is flagged.
- `written_days`: integer or null/absent. `objection`: object or null/absent; `removed_on` null while open.

## Output

```json
{
  "engine": "deadline",
  "rule_version": "1.0.0",
  "input_hash": "<sha256 of canonical inputs>",
  "result": {"status": "ok", "acceptance": "2026-08-01", "basis": "actual_or_deemed",
             "due": "2026-09-15", "interest_from": "2026-09-16", "reason": null},
  "reasons": ["conventions awaiting legal review and flags, one per entry"]
}
```

`status` is `ok` or `open_objection` (dates null, `reason` "acceptance not yet fixed"; keep the invoice in manual review). `basis` is `actual_or_deemed` or `objection_removed`. Always surface `reasons`.
