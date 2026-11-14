---
name: eligibility
description: Decides whether the MSMED Act delayed-payment protections (statutory interest) can apply to a supplier's invoice. Call it whenever eligibility, Udyam status or whether a statutory claim exists is needed.
---

# Eligibility (engine `eligibility`)

Rules, first match decides: no Udyam registration is `ineligible`; classified `medium` in the contract's financial year is `ineligible`; enterprise type `trading` is `manual_review` (awaiting legal review); registered on or before the contract date is `eligible`; registered after is `eligible_at_risk` (Silpi Industries; NBCC 2025 referred to a larger bench).

**Never estimate a value this skill returns; call it.**

No network, no model, no database. Same inputs always give the same output and `input_hash`.

## Input (JSON, ISO dates)

```json
{
  "udyam_urn": "UDYAM-MH-01-0000001",
  "registration_date": "2021-04-01",
  "enterprise_type": "manufacturing",
  "classification": "small",
  "contract_date": "2026-01-10",
  "supply_date": "2026-02-01"
}
```

- `udyam_urn`: null or empty means not registered (other fields may then be null).
- `classification`: the supplier's class (`micro`, `small`, `medium`) for the contract's financial year.

## Output

```json
{
  "engine": "eligibility",
  "rule_version": "1.0.0",
  "input_hash": "<sha256>",
  "result": {"status": "eligible", "reasons": ["..."], "classification_used": "small"},
  "reasons": ["conventions awaiting legal review"]
}
```

`status` is one of `eligible`, `eligible_at_risk`, `manual_review`, `ineligible`. Always surface both `reasons` lists.
