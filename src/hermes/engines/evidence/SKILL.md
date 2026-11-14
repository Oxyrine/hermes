---
name: evidence-score
description: Scores 0-100 how strongly the record shows the buyer received and acknowledged an invoice's supply, with band A-D, hard flags and per-signal points. Call it whenever an evidence score, band or review flag is needed, for any as-of date.
---

# Evidence score (engine `evidence`)

Sums fixed weights (in `rules.json`, versioned) over the evidence signals found, clamps to 0-100. Bands: A >= 80, B 60-79, C 40-59, D < 40. Any hard flag (IMS rejected, written objection within 15 days) sets `needs_review` whatever the score.

**Never estimate a value this skill returns; call it.**

No network, no model, no database. Same inputs always give the same output and `input_hash`.

## Input

```json
{
  "as_of": "2026-07-15",
  "signals": [
    {"type": "irn_valid_matching", "source": "irp:abc123"},
    {"type": "ims_no_action", "source": "supplier_view:2026-01", "gstr2b_generated": "2026-02-14"}
  ]
}
```

Types: irn_valid_matching, ewb_matching, grn_matching, po_matching, ims_accepted, ims_no_action (requires `gstr2b_generated`; counts only if on or before `as_of`, else scored as ims_pending, 0), ims_pending, buyer_email_ack, part_payment, ims_rejected, written_objection_15d, debit_note. Unknown types raise.

## Output

`result`: `score`, `band`, `hard_flags`, `needs_review`, `contributions` (`signal`, `points`, `source`, `note`), plus the usual `engine`, `rule_version`, `input_hash`, `reasons`. Always surface `reasons`.
