from hermes import checks
from hermes.synthetic import gstin_checksum

SCHEMA = {"type": "object", "required": ["n", "sources"], "properties": {
    "n": {"type": "number"}, "g": {"type": "string", "pattern": "^[0-9]{2}[A-Z0-9]{13}$"},
    "items": {"type": "array", "items": {"type": "object"}},
    "sources": {"type": "object", "additionalProperties": {
        "type": "object", "properties": {"page": {"type": "integer"}}}}}}


def test_schema():
    assert checks.check_schema({"n": 1, "sources": {"n": {"page": 1}}}, SCHEMA) == []
    assert checks.check_schema({"sources": {}}, SCHEMA) == ["$.n: required"]
    assert checks.check_schema({"n": "1", "sources": {}}, SCHEMA)
    assert checks.check_schema({"n": True, "sources": {}}, SCHEMA)
    assert checks.check_schema({"n": 1, "g": "bad", "sources": {}}, SCHEMA)
    assert checks.check_schema({"n": 1, "sources": {"n": {"page": 1.5}}}, SCHEMA)
    assert checks.check_schema({"n": 1, "items": [1], "sources": {}}, SCHEMA)


def test_quote_check_voids_missing_quote_only():
    text = "Invoice No:  A/1\n  Total:\t100.00"
    data = {"invoice_no": "A/1", "total": 100, "sources": {
        "invoice_no": {"page": 1, "quote": "Invoice No: A/1"},
        "total": {"page": 1, "quote": "Total: 999.00"}}}
    clean, voided = checks.check_quotes(data, text)
    assert voided == ["total"] and "total" not in clean and clean["invoice_no"] == "A/1"
    assert set(clean["sources"]) == {"invoice_no"}


def test_arithmetic():
    ok = {"taxable_value": 100, "gst_amount": 18, "total": 118,
          "line_items": [{"amount": 60}, {"amount": 40}]}
    assert checks.check_arithmetic(ok) == []
    assert checks.check_arithmetic({**ok, "total": 118.9}) == []  # within 1 rupee
    assert checks.check_arithmetic({**ok, "total": 120})
    assert checks.check_arithmetic({**ok, "line_items": [{"amount": 60}, {"amount": 41}]})


def test_gstin_checksum():
    body = "27AAAAA0000A1Z"
    good = body + gstin_checksum(body)
    assert checks.check_gstin({"supplier_gstin": good}) == []
    bad = body + ("0" if good[-1] != "0" else "1")
    assert checks.check_gstin({"supplier_gstin": bad, "buyer_gstin": good}) == [
        "supplier_gstin: invalid GSTIN"]


def test_cross_source_returns_evidence_not_resolution():
    ext = {"invoice_no": "A/1", "invoice_date": "2026-01-02", "total": 118.0}
    assert checks.check_cross_source(ext, {"invoice_no": "A/1", "invoice_date": "2026-01-02",
                                           "total": "118.00"}) == []
    assert checks.check_cross_source(ext, {"invoice_no": "A/2", "total": 120}) == [
        {"field": "invoice_no", "extracted": "A/1", "record": "A/2"},
        {"field": "total", "extracted": 118.0, "record": 120}]


def test_thresholds():
    assert checks.check_thresholds({"total": 0.95, "invoice_date": 0.9}) == []
    assert checks.check_thresholds({"total": 0.89, "buyer_gstin": 0.5, "po_ref": 0.1}) == [
        "total", "buyer_gstin"]


def test_drafting():
    eng = {"claim": "1,23,456.50", "due": "2026-11-15", "days": 12}
    assert checks.check_drafting("Dear {{buyer}}, Rs 123456.50 was due on 15 November 2026, "
                                 "12 days ago.", eng) == []
    assert checks.check_drafting("Rs 125000 is due", eng) == ["digit not in engine output: 125000"]
    assert checks.check_drafting("We will take legal action.", eng) == [
        "banned phrase: legal action", "banned phrase: take legal"]
    assert checks.check_drafting("The  court   will decide", eng)
