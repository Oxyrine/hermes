from datetime import date, timedelta
from decimal import Decimal

import pytest

from hermes.engines.common import canonical_json, input_hash
from hermes.engines.interest import run
from hermes.engines.interest.engine import add_months

FLAT = [{"effective_from": "2020-01-01", "rate_percent": "5.75"}]


def claim(as_of, start="2025-01-01", principal="1000000", pays=(), rates=FLAT):
    out = run(
        {
            "principal": principal,
            "interest_start": start,
            "as_of": as_of,
            "part_payments": [{"date": d, "amount": a} for d, a in pays],
            "bank_rates": rates,
        }
    )
    return out["result"]


@pytest.mark.parametrize(
    "months,expected",
    [(1, "1014375.00"), (6, "1089409.66"), (12, "1186813.41"), (24, "1408526.08")],
)
def test_golden_vectors(months, expected):
    as_of = add_months(date(2025, 1, 1), months).isoformat()
    assert claim(as_of)["claim_display"] == expected


def test_rests_from_start_do_not_drift():
    assert add_months(date(2025, 1, 31), 1) == date(2025, 2, 28)
    assert add_months(date(2025, 1, 31), 2) == date(2025, 3, 31)
    assert claim("2025-03-31", start="2025-01-31")["full_rests"] == 2
    assert claim("2025-03-30", start="2025-01-31")["full_rests"] == 1


def test_rate_change_affects_only_later_rests():
    changed = FLAT + [{"effective_from": "2025-04-01", "rate_percent": "6.5"}]
    # rests start 01-01, 02-01, 03-01 (rate 5.75), 04-01 (6.5)
    assert Decimal(claim("2025-04-01", rates=changed)["claim"]) == Decimal(
        claim("2025-04-01")["claim"]
    )
    assert claim("2025-05-01", rates=changed)["claim"] != claim("2025-05-01")["claim"]


def test_part_month_is_simple_interest_365():
    # 1 rest, then 10 stub days at 3 * 5.75%
    one = claim("2025-02-01")["claim"]
    got = claim("2025-02-11")["claim"]

    assert Decimal(got) == Decimal(one) * (1 + Decimal("0.1725") * 10 / 365)


def test_part_payment_clears_interest_first_then_balance():
    # pay exactly the interest accrued for a full month, on the rest date: balance unchanged
    interest = "14375"
    r = claim("2025-02-01", pays=[("2025-02-01", interest)])
    assert Decimal(r["claim"]) == 1000000
    # mid-month payment of the whole accrued-so-far interest leaves principal intact
    assert Decimal(claim("2025-01-01", pays=[("2025-01-01", "1000")])["claim"]) == 999000


def test_no_payments_equals_plain_formula():
    bal = 1000000 * (1 + 0.1725 / 12) ** 3
    assert abs(float(claim("2025-04-01")["claim"]) - bal) < 1e-3


def test_payment_exceeding_debt_rejected():
    with pytest.raises(ValueError):
        claim("2025-02-01", pays=[("2025-01-15", "2000000")])


def test_property_monotonic_in_time():
    prev = 0
    for i in range(0, 800, 7):
        c = float(claim((date(2025, 1, 1) + timedelta(days=i)).isoformat())["claim"])
        assert c >= prev
        prev = c


def test_property_part_payment_never_increases_claim():
    base = float(claim("2025-09-20")["claim"])
    for d in ("2025-01-01", "2025-02-01", "2025-03-17", "2025-09-20"):
        for a in ("1", "5000", "100000"):
            assert float(claim("2025-09-20", pays=[(d, a)])["claim"]) <= base


def test_determinism_and_hash():
    inp = {
        "principal": "1000000",
        "interest_start": "2025-01-01",
        "as_of": "2025-06-09",
        "bank_rates": FLAT,
    }
    assert run(inp) == run(inp)
    reordered = dict(reversed(list(inp.items())))
    assert run(reordered)["input_hash"] == run(inp)["input_hash"] == input_hash(inp)
    assert canonical_json(reordered) == canonical_json(inp)


def test_envelope_and_reasons_name_conventions():
    out = run(
        {
            "principal": "1",
            "interest_start": "2025-01-01",
            "as_of": "2025-01-01",
            "bank_rates": FLAT,
        }
    )
    assert set(out) == {"engine", "rule_version", "input_hash", "result", "reasons"}
    text = " ".join(out["reasons"]).lower()
    for word in ("re-read", "stub", "gst", "part payment"):
        assert word in text


def test_no_rounding_inside_computation():
    r = claim("2025-02-11")
    assert len(r["claim"].split(".")[1]) > 2 and r["claim_display"] != r["claim"]
