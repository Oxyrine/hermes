"""Pure checks every model output must pass (product spec section 6). No model, network or DB.

Each check returns what is wrong (empty means it passed); none of them fixes or resolves anything.
"""

import json
import re
from decimal import Decimal, InvalidOperation

from hermes.synthetic.gstin import is_valid_gstin

CONFIDENCE_FLOOR = Decimal("0.9")
AMOUNT_FIELDS = {"total", "taxable_value", "gst_amount", "amount"}
BANNED_PHRASES = (
    "legal action", "take legal", "sue ", "lawsuit", "court", "prosecute", "prosecution",
    "criminal", "arrest", "blacklist", "you are liable", "liable for", "in breach",
    "breach of", "illegal", "unlawful", "fraud", "default judgment", "or else", "final warning",
    "we will recover", "failure to pay will",
)
_TYPES = {"string": str, "boolean": bool, "object": dict, "array": list}


def _dec(v) -> Decimal | None:
    try:
        return Decimal(str(v))
    except InvalidOperation:
        return None


def _norm(s: str) -> str:
    return " ".join(s.split())


def check_schema(data, schema: dict, path: str = "$") -> list[str]:
    """Validate against the JSON-schema subset the product spec uses: type, required, properties,
    items, enum, pattern, additionalProperties (as a schema)."""
    t = schema.get("type")
    if t in ("number", "integer"):
        if isinstance(data, bool) or not isinstance(data, int | float) or (
                t == "integer" and isinstance(data, float) and not data.is_integer()):
            return [f"{path}: expected {t}"]
    elif t in _TYPES and (not isinstance(data, _TYPES[t])):
        return [f"{path}: expected {t}"]
    errs = []
    if "enum" in schema and data not in schema["enum"]:
        errs.append(f"{path}: not in enum")
    if "pattern" in schema and isinstance(data, str) and not re.search(schema["pattern"], data):
        errs.append(f"{path}: does not match pattern")
    if isinstance(data, dict):
        errs += [f"{path}.{k}: required" for k in schema.get("required", []) if k not in data]
        props, extra = schema.get("properties", {}), schema.get("additionalProperties")
        for k, v in data.items():
            sub = props.get(k, extra if isinstance(extra, dict) else None)
            if sub:
                errs += check_schema(v, sub, f"{path}.{k}")
    if isinstance(data, list) and "items" in schema:
        for i, v in enumerate(data):
            errs += check_schema(v, schema["items"], f"{path}[{i}]")
    return errs


def check_quotes(data: dict, text: str) -> tuple[dict, list[str]]:
    """Quote check. Every sources.<field>.quote must occur in the document text after whitespace
    normalisation; a field whose quote is missing is voided (dropped from data and sources).
    Returns (data without voided fields, voided field names)."""
    hay = _norm(text)
    sources = data.get("sources") or {}
    voided = [f for f, s in sources.items()
              if not isinstance(s, dict) or not s.get("quote") or _norm(s["quote"]) not in hay]
    clean = {k: v for k, v in data.items() if k not in voided}
    clean["sources"] = {f: s for f, s in sources.items() if f not in voided}
    return clean, voided


def check_arithmetic(data: dict) -> list[str]:
    """Line items sum to taxable value; taxable value plus GST equals total within one rupee."""
    errs = []
    taxable, gst, total = (_dec(data.get(k)) for k in ("taxable_value", "gst_amount", "total"))
    items = data.get("line_items")
    if items and taxable is not None:
        amounts = [_dec(i.get("amount")) for i in items]
        if None in amounts or abs(sum(amounts) - taxable) > Decimal("0.01"):
            errs.append("line items do not sum to taxable value")
    if None not in (taxable, gst, total) and abs(taxable + gst - total) > Decimal(1):
        errs.append("taxable value plus GST differs from total by more than 1")
    return errs


def check_gstin(data: dict) -> list[str]:
    """Checksum check on every *_gstin field present."""
    return [f"{k}: invalid GSTIN" for k, v in data.items()
            if k.endswith("gstin") and not (isinstance(v, str) and is_valid_gstin(v))]


def check_cross_source(extracted: dict, record: dict, fields=("invoice_no", "invoice_date", "total")):
    """A disagreement with the GST or e-invoice record is evidence of a mismatch, never resolved.
    Returns [{field, extracted, record}]; fields absent from either side are skipped."""
    out = []
    for f in fields:
        a, b = extracted.get(f), record.get(f)
        if a is None or b is None:
            continue
        da, db = (_dec(a), _dec(b)) if f in AMOUNT_FIELDS else (None, None)
        same = abs(da - db) < Decimal("0.005") if da is not None and db is not None else str(a) == str(b)
        if not same:
            out.append({"field": f, "extracted": a, "record": b})
    return out


def check_thresholds(confidences: dict, floor: Decimal = CONFIDENCE_FLOOR) -> list[str]:
    """Fields (amounts, dates, GSTINs) with confidence below the floor, which route to review.
    A sensitive field with no reported confidence also fails."""
    def sensitive(f):
        return f in AMOUNT_FIELDS or f.endswith(("_date", "gstin")) or f == "raised_on"
    return [f for f, c in confidences.items()
            if sensitive(f) and (_dec(c) is None or _dec(c) < floor)]


def _digits(s: str) -> set[Decimal]:
    s = re.sub(r"(?<=\d),(?=\d)", "", s)
    return {Decimal(m) for m in re.findall(r"\d+(?:\.\d+)?", s)}


def check_drafting(draft: str, engine_output) -> list[str]:
    """No number in the draft that is absent from the engine output; no banned phrase."""
    allowed = _digits(json.dumps(engine_output, default=str))
    errs = [f"digit not in engine output: {n}" for n in sorted(_digits(draft) - allowed)]
    low = _norm(draft).lower() + " "
    errs += [f"banned phrase: {p.strip()}" for p in BANNED_PHRASES if p in low]
    return errs
