import calendar
from datetime import date
from decimal import Decimal, localcontext
from pathlib import Path

from hermes.engines.common import CTX, amt, dec, envelope, load_rules, paisa

NAME = "interest"
RULES = load_rules(Path(__file__).parent)


def add_months(d: date, k: int) -> date:
    """d plus k calendar months, clamped to month end. Always counted from the original start."""
    m = d.month - 1 + k
    y, m = d.year + m // 12, m % 12 + 1
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def _statutory_rate(table: list[tuple[date, Decimal]], d: date) -> Decimal:
    """Three times the bank rate in force on d, per annum, as a fraction."""
    rate = None
    for eff, r in table:
        if eff <= d:
            rate = r
    if rate is None:
        raise ValueError(f"no approved bank rate in force on {d}")
    return 3 * rate


def _compute(inputs: dict) -> tuple[Decimal, int]:
    start = date.fromisoformat(inputs["interest_start"])
    as_of = date.fromisoformat(inputs["as_of"])
    if as_of < start:
        raise ValueError("as_of is before interest_start")
    table = sorted(
        (date.fromisoformat(r["effective_from"]), dec(r["rate_percent"]) / 100)
        for r in inputs["bank_rates"]
    )
    pays = sorted(
        (date.fromisoformat(p["date"]), dec(p["amount"])) for p in inputs.get("part_payments", [])
    )
    if any(d > as_of for d, _ in pays):
        raise ValueError("part payment dated after as_of")
    pays.reverse()  # pop() takes the earliest

    bal = dec(inputs["principal"])  # capitalised balance: earns interest
    acc = Decimal(0)  # interest accrued in the current rest period, not yet capitalised

    def pay(amount: Decimal) -> None:
        nonlocal bal, acc
        if amount > bal + acc:
            raise ValueError("part payment exceeds the amount owed")
        from_acc = min(amount, acc)
        acc -= from_acc
        bal -= amount - from_acc

    while pays and pays[-1][0] <= start:  # payments up to the start reduce principal outright
        pay(pays.pop()[1])

    def accrue(frm: date, to: date, annual: Decimal, basis: Decimal) -> None:
        """Accrue frm..to at annual*days/basis on bal; payments inside split the span."""
        nonlocal acc
        at = frm
        while pays and pays[-1][0] < to:
            when, amount = pays.pop()
            acc += bal * annual * (when - at).days / basis
            at = when
            pay(amount)
        acc += bal * annual * (to - at).days / basis

    k, cursor = 0, start
    while add_months(start, k + 1) <= as_of:
        nxt = add_months(start, k + 1)
        # whole-month interest is bal*annual/12, spread pro rata by day within the month
        accrue(cursor, nxt, _statutory_rate(table, cursor), 12 * (nxt - cursor).days)
        bal, acc = bal + acc, Decimal(0)  # the rest: interest joins the balance
        cursor, k = nxt, k + 1
    # part month: simple interest, 365-day basis
    accrue(cursor, as_of, _statutory_rate(table, cursor), Decimal(365))
    while pays:  # payments dated exactly on as_of
        pay(pays.pop()[1])
    return bal + acc, k


def run(inputs: dict) -> dict:
    with localcontext(CTX):
        claim, rests = _compute(inputs)
    return envelope(
        NAME, RULES, inputs,
        {"claim": amt(claim), "claim_display": paisa(claim), "full_rests": rests},
    )
