from datetime import date
from pathlib import Path

from hermes.engines.common import envelope, load_rules

NAME = "eligibility"
RULES = load_rules(Path(__file__).parent)


def _decide(inputs: dict) -> tuple[str, list[str]]:
    """First matching rule decides. supply_date is carried in the inputs (hashed) but no v0 rule uses it."""
    if not inputs.get("udyam_urn"):
        return "ineligible", ["No Udyam registration: evidence financing only."]
    if inputs["classification"] == "medium":
        return "ineligible", [
            (
                "Classified medium in the contract's financial year: the delayed-payment chapter "
                "covers micro and small enterprises only."
            )
        ]
    if inputs["enterprise_type"] == "trading":
        return "manual_review", [
            "Trader registration: awaiting legal review on whether it carries delayed-payment rights."
        ]
    if date.fromisoformat(inputs["registration_date"]) <= date.fromisoformat(inputs["contract_date"]):
        return "eligible", ["Udyam registration on or before the contract date."]
    return "eligible_at_risk", [
        (
            "Registered after the contract date: Silpi Industries said registration must pre-date "
            "the contract; NBCC (2025) referred that question to a larger bench. "
            "Lender policy decides whether to finance."
        )
    ]


def run(inputs: dict) -> dict:
    status, reasons = _decide(inputs)
    return envelope(
        NAME, RULES, inputs,
        {"status": status, "reasons": reasons, "classification_used": inputs.get("classification")},
    )
