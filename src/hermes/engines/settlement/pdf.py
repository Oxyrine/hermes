from fpdf import FPDF


def _lines(result: dict) -> list[tuple[str, str]]:
    pack = result["dispute_pack"]
    out = [("h", "Dispute pack (draft for a person to file; Hermes never submits)"),
           ("t", f"Settlement date: {result['as_of']}")]
    out += [("h", "Document index")] + [
        ("t", f"{d['id']}  {d['title']}  (source: {d['source']})") for d in pack["document_index"]]
    out += [("h", "Chronology")] + [("t", f"{r['date']}  {r['event']}") for r in pack["chronology"]]
    cc = pack["claim_computation"]
    out += [("h", "Claim computation")] + [
        ("t", f"{r['item']}: INR {r['amount']}  (source: {r['source']})") for r in cc["rows"]]
    out += [("t", f"Run: {r['engine']} rule version {r['rule_version']} inputs {r['input_hash']}")
            for r in cc["runs"]]
    out += [("h", "Evidence table")] + [
        ("t", f"{r['signal']}: {r['points']} points  (source: {r['source']})")
        for r in pack["evidence_table"]]
    return out


def render_pdf(result: dict) -> bytes:
    """Renders only strings already in the pack JSON, so every figure in the PDF is in the JSON.
    Takes the envelope's `result`."""
    pdf = FPDF()
    pdf.set_compression(False)  # plain content streams: text is checkable
    pdf.add_page()
    for kind, text in _lines(result):
        pdf.set_font("Helvetica", "B" if kind == "h" else "", 12 if kind == "h" else 9)
        pdf.multi_cell(0, 6, text, new_x="LMARGIN", new_y="NEXT")
    return bytes(pdf.output())
