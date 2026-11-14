import re
from datetime import date
from decimal import Decimal, localcontext
from pathlib import Path

from hermes.engines.common import CTX, amt, dec, envelope, load_rules, paisa

NAME = "settlement"
RULES = load_rules(Path(__file__).parent)


def _src(env: dict) -> dict:
    return {"engine": env["engine"], "rule_version": env["rule_version"],
            "input_hash": env["input_hash"], "result": env["result"]}


def _render(template: str, values: dict) -> str:
    return re.sub(r"\{\{(\w+)\}\}", lambda m: values[m.group(1)], template)  # KeyError if unnamed


def run(inputs: dict) -> dict:
    """Inputs: invoice {invoice_no, invoice_date, principal (outstanding), supplier_name,
    buyer_name}, as_of, discount_percent, agreed_costs, optional offer_override, optional
    documents [{id, title, source}], and the full envelopes of eligibility, deadline,
    collateral (as_of = settlement date), evidence and, unless ineligible, interest."""
    inv, as_of = inputs["invoice"], date.fromisoformat(inputs["as_of"])
    elig, dl, col, ev = (inputs[k] for k in ("eligibility", "deadline", "collateral", "evidence"))
    if dl["result"]["status"] != "ok":
        raise ValueError("deadline is not settled; no settlement computation")
    if col["result"]["date"] != inputs["as_of"]:
        raise ValueError("collateral run is not for the settlement date")
    ineligible = elig["result"]["status"] == "ineligible"
    with localcontext(CTX):
        principal = dec(inv["principal"])
        due = date.fromisoformat(dl["result"]["due"])
        days_late = max((as_of - due).days, 0)
        discount = dec(inputs.get("discount_percent", "0"))
        if not 0 <= discount <= 100:
            raise ValueError("discount_percent must be between 0 and 100")
        floor = dec(col["result"]["exposure"]) + dec(inputs.get("agreed_costs", "0"))
        runs = [elig, dl, col, ev]
        if ineligible:  # no statutory claim: no interest figure, no discount to take
            interest = None
            offer = principal
        else:
            runs.insert(2, inputs["interest"])
            interest = max(dec(inputs["interest"]["result"]["claim"]) - principal, Decimal(0))
            offer = principal + interest * (1 - discount / 100)
        if "offer_override" in inputs:  # supplier-chosen figure, still checked against the floor
            offer = dec(inputs["offer_override"])
        needs_consent = offer < floor

        values = {
            "buyer_name": inv["buyer_name"], "supplier_name": inv["supplier_name"],
            "invoice_no": inv["invoice_no"], "invoice_date": inv["invoice_date"],
            "principal": paisa(principal), "acceptance_date": dl["result"]["acceptance"],
            "due_date": dl["result"]["due"], "as_of": inputs["as_of"],
            "days_late": str(days_late),
            "interest_to_date": "not applicable" if interest is None else paisa(interest),
            "offer": paisa(offer), "discount_percent": amt(discount),
        }
        statement = {
            "invoice_no": inv["invoice_no"], "invoice_date": inv["invoice_date"],
            "acceptance_date": dl["result"]["acceptance"], "due_date": dl["result"]["due"],
            "days_late": str(days_late),
            "interest_to_date": None if interest is None else paisa(interest),
            "notes": RULES["notes"],
        }
        rows = [{"item": "principal", "amount": paisa(principal), "source": "invoice"}]
        if interest is not None:
            claim = dec(inputs["interest"]["result"]["claim"])
            rows += [
                {"item": "statutory_claim", "amount": paisa(claim), "source": "interest"},
                {"item": "statutory_interest", "amount": paisa(interest), "source": "interest"},
            ]
        events = [
            (inv["invoice_date"], "Invoice issued"),
            (dl["result"]["acceptance"], "Goods or services accepted"),
            (dl["result"]["due"], "Payment due"),
            (inputs["as_of"], "Pack prepared"),
        ]
        pack = {
            "document_index": [
                {"id": d["id"], "title": d["title"], "source": d["source"]}
                for d in inputs.get("documents", [])
            ],
            "chronology": [{"date": d, "event": e} for d, e in sorted(events)],
            "claim_computation": {"rows": rows, "runs": [_src(r) for r in runs]},
            "evidence_table": [
                {"signal": c["signal"], "points": str(c["points"]), "source": c["source"]}
                for c in ev["result"]["contributions"]
            ],
        }
        result = {
            "as_of": inputs["as_of"],
            "eligibility": elig["result"]["status"],
            "floor": amt(floor), "floor_display": paisa(floor),
            "offer": amt(offer), "offer_display": paisa(offer),
            "interest": None if interest is None else amt(interest),
            "discount_percent": amt(discount),
            "needs_lender_consent": needs_consent,
            "marker": "needs lender consent" if needs_consent else None,
            "buyer_statement": statement,
            "letter": {"template": RULES["letter_template"], "values": values,
                       "text": _render(RULES["letter_template"], values)},
            "dispute_pack": pack,
        }
    return envelope(NAME, RULES, inputs, result)
