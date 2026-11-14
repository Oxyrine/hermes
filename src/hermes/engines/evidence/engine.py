from datetime import date
from pathlib import Path

from hermes.engines.common import envelope, load_rules

NAME = "evidence"
RULES = load_rules(Path(__file__).parent)


def _band(score: int) -> str:
    return next(b for b, floor in RULES["bands"] if score >= floor)


def run(inputs: dict) -> dict:
    as_of = date.fromisoformat(inputs["as_of"])
    weights = RULES["weights"]
    contributions, flags, total = [], [], 0
    for s in inputs["signals"]:
        kind = s["type"]
        if kind not in weights:
            raise ValueError(f"unknown signal type {kind!r}")
        note = ""
        if kind == "ims_no_action" and date.fromisoformat(s["gstr2b_generated"]) > as_of:
            kind, note = "ims_pending", "GSTR-2B not yet generated at as-of date; scored as pending"
        w = weights[kind]
        total += w["points"]
        if w["hard_flag"]:
            flags.append(kind)
        contributions.append(
            {"signal": kind, "points": w["points"], "source": s["source"], "note": note}
        )
    score = max(0, min(100, total))
    result = {
        "score": score,
        "band": _band(score),
        "hard_flags": flags,
        "needs_review": bool(flags),
        "contributions": contributions,
    }
    return envelope(NAME, RULES, inputs, result)
