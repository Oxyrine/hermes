import pytest

from hermes.engines.eligibility import run

BASE = {
    "udyam_urn": "UDYAM-MH-01-0000001",
    "registration_date": "2021-04-01",
    "enterprise_type": "manufacturing",
    "classification": "small",
    "contract_date": "2026-01-10",
    "supply_date": "2026-02-01",
}


@pytest.mark.parametrize(
    "change,status",
    [
        ({}, "eligible"),
        ({"registration_date": "2026-01-10"}, "eligible"),
        ({"registration_date": "2026-01-11"}, "eligible_at_risk"),
        ({"udyam_urn": None, "registration_date": None, "classification": None}, "ineligible"),
        ({"classification": "medium"}, "ineligible"),
        ({"enterprise_type": "trading"}, "manual_review"),
        # order: medium beats trading; trading beats a late registration
        ({"classification": "medium", "enterprise_type": "trading"}, "ineligible"),
        ({"enterprise_type": "trading", "registration_date": "2027-01-01"}, "manual_review"),
    ],
)
def test_status(change, status):
    out = run({**BASE, **change})
    assert out["result"]["status"] == status
    assert out["result"]["reasons"]
    assert out["result"]["classification_used"] == (change.get("classification", "small"))


def test_reason_text_and_envelope():
    late = run({**BASE, "registration_date": "2026-03-01"})
    text = late["result"]["reasons"][0]
    assert "Silpi Industries" in text and "NBCC (2025)" in text and "larger bench" in text
    assert "legal review" in run({**BASE, "enterprise_type": "trading"})["result"]["reasons"][0]
    assert late["rule_version"] == "1.0.0" and len(late["input_hash"]) == 64
    assert run(BASE) == run(dict(BASE))
