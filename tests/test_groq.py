from hermes import groq


def test_pdf_text_is_read_from_tj_operators():
    pdf = b"stream\nBT (PO No: PO-0001) Tj T* ET\nBT (a \\(b\\) c) Tj ET\nendstream"
    assert groq.document_text(pdf, "application/pdf") == "PO No: PO-0001\na (b) c"


def test_tool_model_maps_turns_and_ids(monkeypatch):
    sent = {}

    class R:
        status_code, text = 200, ""
        def raise_for_status(self): pass
        def json(self):
            return {"choices": [{"message": {"content": None, "tool_calls": [
                {"function": {"name": "read_invoice", "arguments": "{}"}}]}}], "usage": {"prompt_tokens": 3, "completion_tokens": 1}}

    monkeypatch.setattr(groq, "_post", lambda key, body, timeout: sent.update(body) or R())
    m = groq.groq_tool_model("k", "llama", Exception)
    out = m("sys", [{"role": "user", "text": "go"},
                    {"role": "model", "text": "", "calls": [{"name": "read_invoice", "args": {}}]},
                    {"role": "tool", "name": "read_invoice", "result": {"ok": 1}}], [{"name": "read_invoice"}])
    roles = [x["role"] for x in sent["messages"]]
    assert roles == ["system", "user", "assistant", "tool"]
    assert sent["messages"][3]["tool_call_id"] == sent["messages"][2]["tool_calls"][0]["id"]
    assert out["calls"] == [{"name": "read_invoice", "args": {}, "sig": None}] and out["tokens_in"] == 3
