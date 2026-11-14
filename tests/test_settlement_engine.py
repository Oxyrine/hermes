import json
import re

import pytest

from hermes.engines.settlement import render_pdf, run


def env(engine, result):
    return {"engine": engine, "rule_version": "1.0.0", "input_hash": engine + "-hash",
            "result": result, "reasons": []}


def inputs(status="eligible", **kw):
    d = {
        "invoice": {"invoice_no": "INV-1", "invoice_date": "2025-12-01", "principal": "1000000",
                    "supplier_name": "Acme Works", "buyer_name": "Big Buyer Ltd"},
        "as_of": "2026-07-15", "discount_percent": "0", "agreed_costs": "5000",
        "documents": [{"id": "D1", "title": "Invoice", "source": "upload"}],
        "eligibility": env("eligibility", {"status": status}),
        "deadline": env("deadline", {"status": "ok", "acceptance": "2025-12-05",
                                     "due": "2026-01-19"}),
        "interest": env("interest", {"claim": "1089409.66"}),
        "collateral": env("collateral", {"date": "2026-07-15", "exposure": "800000"}),
        "evidence": env("evidence", {"contributions": [
            {"signal": "IRN valid", "points": 15, "source": "IRP"}]}),
    }
    return d | kw


def test_floor_offer_and_discount():
    r = run(inputs(discount_percent="50"))["result"]
    assert r["floor"] == "805000"
    assert r["interest"] == "89409.66"
    assert r["offer_display"] == "1044704.83"
    assert not r["needs_lender_consent"]
    assert r["buyer_statement"]["days_late"] == "177"
    assert len(r["buyer_statement"]["notes"]) == 2


def test_below_floor_is_marked_not_refused():
    r = run(inputs(offer_override="700000"))["result"]
    assert r["needs_lender_consent"] and r["marker"] == "needs lender consent"
    assert r["offer"] == "700000"


def test_ineligible_has_no_interest():
    i = inputs("ineligible")
    del i["interest"]
    out = run(i)
    assert out["result"]["interest"] is None
    assert out["result"]["buyer_statement"]["interest_to_date"] is None
    assert "89409" not in json.dumps(out)


def test_letter_fully_filled_and_runs_cited():
    out = run(inputs())
    assert "{{" not in out["result"]["letter"]["text"]
    runs = out["result"]["dispute_pack"]["claim_computation"]["runs"]
    assert {r["engine"] for r in runs} == {"eligibility", "deadline", "interest", "collateral",
                                          "evidence"}
    assert all(r["rule_version"] for r in runs)
    assert run(inputs())["input_hash"] == out["input_hash"]


def test_pdf_numbers_are_in_json():
    result = run(inputs())["result"]
    pdf = render_pdf(result)
    assert pdf.startswith(b"%PDF")
    text = b" ".join(re.findall(rb"\(([^)]*)\)", pdf)).decode("latin-1")
    blob = json.dumps(result["dispute_pack"]) + result["as_of"]
    text = re.sub(r"D:\d+", "", text)  # PDF creation-date metadata
    nums = re.findall(r"\d[\d.,-]*\d|\d", text)
    assert "1089409.66" in text
    assert all(n in blob for n in nums if len(n) > 4 or "." in n)


def test_guards():
    i = inputs(collateral=env("collateral", {"date": "2026-07-01", "exposure": "1"}))
    with pytest.raises(ValueError):
        run(i)
    with pytest.raises(ValueError):
        run(inputs(discount_percent="101"))
