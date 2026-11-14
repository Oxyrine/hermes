from datetime import date, timedelta
from pathlib import Path

from hermes.engines.common import envelope, load_rules

NAME = "deadline"
RULES = load_rules(Path(__file__).parent)
WINDOW_DAYS = 15  # objection must be raised within this many days of delivery
TERM_CAP_DAYS = 45
DEFAULT_TERM_DAYS = 15


def _compute(inputs: dict) -> tuple[dict, list[str]]:
    delivery = date.fromisoformat(inputs["delivery"])
    extra: list[str] = []
    inst = inputs.get("instalment_dates")
    if inst:
        delivery = max(date.fromisoformat(d) for d in inst)
        extra.append("Delivery in instalments: v0 uses the last goods-receipt date.")
    days = inputs.get("written_days")
    if days is not None and (isinstance(days, bool) or not isinstance(days, int) or days < 0):
        raise ValueError("written_days must be a non-negative integer or null")
    ob = inputs.get("objection")
    acceptance, basis = delivery, "actual_or_deemed"
    if ob:
        raised = date.fromisoformat(ob["raised_on"])
        removed = date.fromisoformat(ob["removed_on"]) if ob.get("removed_on") else None
        if removed and removed < raised:
            raise ValueError("objection removed before it was raised")
        if raised <= delivery + timedelta(days=WINDOW_DAYS):
            if removed is None:
                reason = "acceptance not yet fixed"
                return (
                    {"status": "open_objection", "acceptance": None, "basis": None,
                     "due": None, "interest_from": None, "reason": reason},
                    [*extra, reason],
                )
            acceptance, basis = removed, "objection_removed"
        else:
            extra.append("Objection raised after the 15-day window: ignored.")
    term = TERM_CAP_DAYS if days is None else min(days, TERM_CAP_DAYS)
    if days is None:
        term = DEFAULT_TERM_DAYS
    elif days > TERM_CAP_DAYS:
        extra.append(f"Written term of {days} days capped at {TERM_CAP_DAYS}.")
    due = acceptance + timedelta(days=term)
    return (
        {"status": "ok", "acceptance": acceptance.isoformat(), "basis": basis,
         "due": due.isoformat(), "interest_from": (due + timedelta(days=1)).isoformat(),
         "reason": None},
        extra,
    )


def run(inputs: dict) -> dict:
    result, extra = _compute(inputs)
    out = envelope(NAME, RULES, inputs, result)
    out["reasons"] += extra
    return out
