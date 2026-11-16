import random
from datetime import date, timedelta
from decimal import Decimal
from itertools import pairwise

from hermes.engines.collateral import run
from hermes.engines.interest import run as interest

BASE = {
    "eligibility": "eligible", "band": "B", "principal": "1000000", "due_date": "2026-01-31",
    "statutory_claim": "1100000", "advance": "700000", "funded_on": "2026-02-01",
    "lender_rate_percent": "12", "bank_rate_percent": "5.75", "as_of": "2026-03-01",
}


def res(**kw):
    return run({**BASE, **kw})["result"]


def test_claim_choice():
    assert Decimal(res()["claim_value"]) == 1100000
    assert Decimal(res(eligibility="ineligible")["claim_value"]) == 1000000
    assert Decimal(res(as_of="2026-01-31", advance="0")["claim_value"]) == 1000000  # not yet due
    paid = res(eligibility="ineligible", payments=[{"date": "2026-02-10", "amount": "100000"}])
    assert Decimal(paid["claim_value"]) == 900000


def test_exposure_and_ltv():
    r = res(as_of="2026-03-01")  # exactly one month
    assert Decimal(r["exposure"]) == 700000 * Decimal("1.01")
    assert Decimal(r["ltv"]) == Decimal(r["exposure"]) / 1100000
    stub = res(as_of="2026-03-11")  # ten-day stub
    want = 707000 * (1 + Decimal("0.12") * 10 / 365)
    assert abs(Decimal(stub["exposure"]) - want) < Decimal("1e-9")


def test_alerts():
    assert res()["alerts"] == []
    assert "ltv_above_band_limit" in res(band="D")["alerts"]
    assert "ltv_above_band_limit" in res(statutory_claim="800000")["alerts"]
    assert "cushion erodes with time" in res(lender_rate_percent="18")["alerts"]
    flag = {"date": "2026-02-15", "kind": "x"}
    assert res(hard_flags=[flag])["alerts"] == ["hard_flag_after_funding"]
    assert res(hard_flags=[{**flag, "date": "2026-01-15"}])["alerts"] == []
    assert res(advance="0", hard_flags=[flag])["alerts"] == []


def test_waterfall_sums_exactly():
    exp = Decimal(res()["exposure"])
    for receipts in ["100", "710000", "1200000"]:
        w = res(receipts=receipts, agreed_costs="5000")["waterfall"]
        assert sum(Decimal(v) for v in w.values()) == Decimal(receipts)
    w = res(receipts="1200000", agreed_costs="5000")["waterfall"]
    assert Decimal(w["lender_exposure"]) == exp and Decimal(w["costs"]) == 5000
    assert Decimal(w["supplier"]) == 1200000 - exp - 5000
    assert set(w) == {"lender_exposure", "costs", "supplier"}  # no interest-linked fee


def test_series_and_envelope():
    claims = {(date(2026, 3, 1) + timedelta(i)).isoformat(): "1100000" for i in range(3)}
    inp = {k: v for k, v in BASE.items() if k not in ("as_of", "statutory_claim")}
    out = run({**inp, "range": {"from": "2026-03-01", "to": "2026-03-03"}, "statutory_claims": claims})
    assert [d["date"] for d in out["result"]["series"]] == ["2026-03-01", "2026-03-02", "2026-03-03"]
    assert out["rule_version"] == "1.1.0" and len(out["input_hash"]) == 64 and out["reasons"]


def test_ltv_falls_when_lender_rate_below_3x_bank_rate():
    rng = random.Random(7)
    for _ in range(30):
        bank = Decimal(rng.randint(400, 900)) / 100
        lender = Decimal(rng.randint(100, int(bank * 3 * 100) - 100)) / 100  # below 3 x bank
        start = date(2025, 1, 1) + timedelta(rng.randint(0, 400))
        days = [start + timedelta(i) for i in range(1, 200)]
        claims = {
            d.isoformat(): interest({
                "principal": "1000000", "interest_start": start.isoformat(),
                "as_of": d.isoformat(),
                "bank_rates": [{"effective_from": "2020-01-01", "rate_percent": str(bank)}],
            })["result"]["claim"]
            for d in days
        }
        out = run({
            "eligibility": "eligible", "band": "A", "principal": "1000000",
            "due_date": start.isoformat(), "advance": "800000", "funded_on": start.isoformat(),
            "lender_rate_percent": str(lender), "bank_rate_percent": str(bank),
            "range": {"from": days[0].isoformat(), "to": days[-1].isoformat()},
            "statutory_claims": claims,
        })
        ltv = [Decimal(d["ltv"]) for d in out["result"]["series"]]
        assert all(b <= a for a, b in pairwise(ltv)), (bank, lender, start)
