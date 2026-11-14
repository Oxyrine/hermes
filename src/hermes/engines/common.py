"""Shared engine plumbing. Every engine (src/hermes/engines/<name>/) follows one pattern:

- a package exposing `run(inputs: dict) -> dict`, with a `rules.json` beside it holding
  `{"version": "<semver>", "reasons": [...]}`;
- no network, no model calls, no database; Decimal at 28 digits; amounts cross JSON as strings;
- output is `envelope(...)`: engine name, rule version, SHA-256 of the canonical inputs,
  the result and a list of reasons (conventions awaiting legal review, etc.);
- a `SKILL.md` beside the package says when to call it, its schemas, and that the value is
  never to be estimated.
Changing an engine's .py files or rules.json requires a rule version bump; the guard is
tests/test_rule_versions.py, and `python -m hermes.engines.manifest` records the new hash.
"""

import hashlib
import json
from decimal import Context, Decimal
from pathlib import Path

CTX = Context(prec=28)  # engines do all arithmetic through this context's precision


def canonical_json(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def input_hash(inputs: dict) -> str:
    return hashlib.sha256(canonical_json(inputs).encode()).hexdigest()


def dec(s) -> Decimal:
    """Parse an amount from JSON. Strings only: floats would smuggle in binary error."""
    if not isinstance(s, str):
        raise TypeError(f"amount must be a string, got {s!r}")
    return Decimal(s)


def amt(d: Decimal) -> str:
    """Decimal to JSON string, full precision, no exponent."""
    return format(d, "f")


def paisa(d: Decimal) -> str:
    """Display rounding only; never feed this back into a computation."""
    return format(d.quantize(Decimal("0.01")), "f")


def load_rules(engine_dir: Path) -> dict:
    return json.loads((engine_dir / "rules.json").read_text(encoding="utf-8"))


def envelope(engine: str, rules: dict, inputs: dict, result: dict) -> dict:
    return {
        "engine": engine,
        "rule_version": rules["version"],
        "input_hash": input_hash(inputs),
        "result": result,
        "reasons": list(rules["reasons"]),
    }
