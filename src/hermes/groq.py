"""Groq fallback (manual live runs only): used when Gemini's free tier is out of quota or capacity.
Not a pinned production model (see models.toml [fallback]); a run on it is labelled as such.
Groq is text-only, so a PDF is read as its text. ponytail: the synthetic PDFs keep their text in
uncompressed `(...) Tj` operators; a compressed or scanned PDF would need a real extractor (pypdf)."""

import json
import os
import re

from hermes.llm import PINS, Request

URL = "https://api.groq.com/openai/v1/chat/completions"
_TJ = re.compile(rb"\(((?:\\.|[^\\)])*)\)\s*Tj")
_ESC = re.compile(rb"\\(.)")


def document_text(data: bytes, mime: str) -> str:
    if mime != "application/pdf":
        return data.decode("utf-8", errors="replace")
    lines = [_ESC.sub(rb"\1", m[1]).decode("latin-1") for m in _TJ.finditer(data)]
    if not lines:
        raise ValueError("no extractable text in this PDF")
    return "\n".join(lines)


def _post(key: str, body: dict, timeout: float):
    import httpx

    return httpx.post(URL, headers={"Authorization": f"Bearer {key}"}, json=body, timeout=timeout)


class GroqBackend:
    """A ModelClient backend: JSON-mode chat completion over the document's text."""

    def __init__(self, api_key: str | None = None, timeout: float = 100):
        self.key, self.timeout = api_key or os.environ["GROQ_API_KEY"], timeout

    def generate(self, req: Request) -> dict:
        from hermes.llm import RateLimited

        body = {"model": req.model, "temperature": req.temperature,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": req.system + "\nAnswer with one JSON object matching this "
                     "JSON Schema:\n" + json.dumps(req.schema)},
                    {"role": "user", "content": req.prompt + "\n\n--- document ---\n"
                     + document_text(req.document.data, req.document.mime)}]}
        r = _post(self.key, body, self.timeout)
        if r.status_code == 429:
            raise RateLimited(daily="per day" in r.text.lower())
        if r.status_code in (500, 503):
            raise RateLimited()
        r.raise_for_status()
        return json.loads(r.json()["choices"][0]["message"]["content"])


def groq_tool_model(api_key: str, name: str | None, limit_exc: type[Exception], timeout: float = 60):
    """The loop's model on Groq (OpenAI-style tool calling), the same shape as llm.gemini_tool_model."""
    name = name or PINS["groq"]

    def model(system: str, msgs: list[dict], decls: list[dict]) -> dict:
        out, pending = [{"role": "system", "content": system}], []
        for m in msgs:
            if m["role"] == "tool":
                i = next((n for n, c in enumerate(pending) if c["function"]["name"] == m["name"]), None)
                cid = pending.pop(i)["id"] if i is not None else "call_unmatched"
                out.append({"role": "tool", "tool_call_id": cid, "content": json.dumps(m["result"])})
            elif m["role"] == "user":
                out.append({"role": "user", "content": m["text"]})
            else:
                pending = [{"id": f"call_{len(out)}_{n}", "type": "function",
                            "function": {"name": c["name"], "arguments": json.dumps(c.get("args") or {})}}
                           for n, c in enumerate(m.get("calls", []))]
                out.append({"role": "assistant", "content": m.get("text") or None,
                            **({"tool_calls": list(pending)} if pending else {})})  # a copy: tool turns pop `pending`
        r = _post(api_key, {"model": name, "messages": out,
                            "tools": [{"type": "function", "function": d} for d in decls]}, timeout)
        if r.status_code == 429:  # "PerDay" marks the daily quota for the loop's retry logic
            raise limit_exc(("PerDay " if "per day" in r.text.lower() else "") + r.text)
        r.raise_for_status()
        body = r.json()
        msg, use = body["choices"][0]["message"], body.get("usage", {})
        return {"calls": [{"name": c["function"]["name"], "args": json.loads(c["function"]["arguments"] or "{}"),
                           "sig": None} for c in msg.get("tool_calls") or []],
                "text": msg.get("content") or "",
                "tokens_in": use.get("prompt_tokens"), "tokens_out": use.get("completion_tokens")}

    model.name = name
    return model
