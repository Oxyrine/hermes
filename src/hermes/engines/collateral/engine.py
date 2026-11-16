import calendar
from datetime import date, timedelta
from decimal import Decimal, localcontext
from pathlib import Path

from hermes.engines.common import CTX, amt, dec, envelope, load_rules, paisa

NAME = "collateral"
RULES = load_rules(Path(__file__).parent)
POLICY = RULES["policy"]


def add_months(d: date, k: int) -> date:
    """d plus k calendar months, clamped to month end (same convention as the interest engine)."""
    m = d.month - 1 + k
    y, m = d.year + m // 12, m % 12 + 1
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def _exposure(advance: Decimal, funded: date, as_of: date, rate: Decimal) -> Decimal:
    k = 0
    while add_months(funded, k + 1) <= as_of:
        k += 1
    bal = advance * (1 + rate / 12) ** k
    return bal + bal * rate * (as_of - add_months(funded, k)).days / 365  # part-month stub


def _day(inputs: dict, as_of: date, statutory: Decimal) -> dict:
    paid = sum(
        (dec(p["amount"]) for p in inputs.get("payments", [])
         if date.fromisoformat(p["date"]) <= as_of),
        Decimal(0),
    )
    unpaid = dec(inputs["principal"]) - paid
    overdue = as_of > date.fromisoformat(inputs["due_date"])
    claim = statutory if inputs["eligibility"] != "ineligible" and overdue else unpaid

    advance = dec(inputs.get("advance", "0"))
    funded = date.fromisoformat(inputs["funded_on"]) if inputs.get("funded_on") else None
    is_funded = advance > 0 and funded is not None and funded <= as_of
    lender_rate = dec(inputs["lender_rate_percent"])
    exposure = _exposure(advance, funded, as_of, lender_rate / 100) if is_funded else Decimal(0)
    ltv = exposure / claim if is_funded and claim > 0 else None

    limit = dec(POLICY["advance_rate"][inputs["band"]])
    alerts = []
    if ltv is not None and ltv > limit + dec(POLICY["ltv_alert_margin"]):
        alerts.append("ltv_above_band_limit")
    if is_funded and lender_rate > dec(POLICY["cushion_rate_multiple"]) * dec(inputs["bank_rate_percent"]):
        alerts.append("cushion erodes with time")
    if is_funded and any(
        funded < date.fromisoformat(f["date"]) <= as_of for f in inputs.get("hard_flags", [])
    ):
        alerts.append("hard_flag_after_funding")
    return {
        "date": as_of.isoformat(),
        "claim_value": amt(claim),
        "claim_display": paisa(claim),
        "exposure": amt(exposure),
        "exposure_display": paisa(exposure),
        "ltv": None if ltv is None else amt(ltv),
        "advance_rate": amt(limit),
        "alerts": alerts,
    }


def _waterfall(receipts: Decimal, exposure: Decimal, costs: Decimal) -> dict:
    to_lender = min(receipts, exposure)
    to_costs = min(receipts - to_lender, costs)
    return {
        "lender_exposure": amt(to_lender),
        "costs": amt(to_costs),
        "supplier": amt(receipts - to_lender - to_costs),  # all statutory interest lands here
    }


def run(inputs: dict) -> dict:
    """One day (as_of + statutory_claim) or a daily series (range {from,to} + statutory_claims
    keyed by ISO date). The statutory claim comes from the interest engine; it is an input here."""
    with localcontext(CTX):
        if "range" in inputs:
            d, end = (date.fromisoformat(inputs["range"][k]) for k in ("from", "to"))
            series = []
            while d <= end:
                series.append(_day(inputs, d, dec(inputs["statutory_claims"][d.isoformat()])))
                d += timedelta(days=1)
            result = {"series": series}
        else:
            result = _day(inputs, date.fromisoformat(inputs["as_of"]), dec(inputs["statutory_claim"]))
            if "receipts" in inputs:
                result["waterfall"] = _waterfall(
                    dec(inputs["receipts"]), dec(result["exposure"]),
                    dec(inputs.get("agreed_costs", "0")),
                )
    return envelope(NAME, RULES, inputs, result)
