"""The model client: the only place a model is called (product spec section 6, ticket 17).

Enforces the two pinned free-tier models, structured output (one retry, then review), temperature
zero for extraction and detection, documents passed as files, the response cache, backoff on rate
limits, and the synthetic-only guard. Logs carry task, model and a hash prefix, never content.
"""

import base64
import hashlib
import json
import logging
import os
import time
import tomllib
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from hermes.checks import check_schema

log = logging.getLogger("hermes.llm")
PINS = tomllib.loads(Path(__file__).with_name("models.toml").read_text(encoding="utf-8"))["models"]
ALLOWED_MODELS = frozenset(PINS.values())
ZERO_TEMPERATURE_TASKS = ("classify", "extract", "detect")  # task-name prefixes
RETRY_AFTER = (2, 8, 30)  # seconds between rate-limit retries


class ModelNotAllowed(ValueError):
    """A model other than the two pinned free-tier ones was requested."""


class DataModeRefused(PermissionError):
    """Synthetic mode and the document is not in the synthetic manifest."""


class RateLimited(Exception):
    def __init__(self, daily: bool = False):
        super().__init__("daily limit exhausted" if daily else "rate limited")
        self.daily = daily


@dataclass(frozen=True)
class Document:
    data: bytes
    mime: str = "application/pdf"

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.data).hexdigest()


@dataclass(frozen=True)
class Request:
    task: str
    model: str
    system: str
    prompt: str
    document: Document
    schema: dict
    temperature: float


@dataclass
class Result:
    status: str  # "ok" or "review"
    data: dict | None = None
    reason: str | None = None
    model: str | None = None
    cached: bool = False


class Backend(Protocol):
    def generate(self, req: Request) -> dict: ...


class MemoryCache:
    def __init__(self):
        self.rows: dict[str, dict] = {}

    def get(self, key: str) -> dict | None:
        return self.rows.get(key)

    def put(self, key, task, model, prompt_version, doc_hash, response):
        self.rows[key] = response


class PgCache:
    """Cache in the model_cache table (global, no tenant)."""

    def __init__(self, conn):
        self.conn = conn

    def get(self, key):
        row = self.conn.execute("SELECT response FROM model_cache WHERE cache_key=%s", (key,)).fetchone()
        return row[0] if row else None

    def put(self, key, task, model, prompt_version, doc_hash, response):
        self.conn.execute(
            "INSERT INTO model_cache (cache_key, task, model, prompt_version, doc_hash, response)"
            " VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT (cache_key) DO NOTHING",
            (key, task, model, prompt_version, doc_hash, json.dumps(response)))


@dataclass
class FakeModel:
    """Returns ground truth by document hash: truth[doc_hash] or truth[(task, doc_hash)].
    A value that is an Exception instance is raised; a list is consumed one entry per call."""
    truth: dict
    calls: list = field(default_factory=list)

    def generate(self, req: Request) -> dict:
        self.calls.append(req)
        h = req.document.sha256
        out = self.truth.get((req.task, h), self.truth.get(h))
        if isinstance(out, list):
            out = out.pop(0)
        if isinstance(out, Exception):
            raise out
        if out is None:
            raise KeyError(f"fake model has no truth for {req.task} {h[:12]}")
        return out


class GeminiBackend:
    """Gemini API over REST (v1beta). The key comes from GEMINI_API_KEY; manual runs only."""

    def __init__(self, api_key: str | None = None, timeout: float = 100):
        self.key, self.timeout = api_key or os.environ["GEMINI_API_KEY"], timeout

    def generate(self, req: Request) -> dict:
        body = {
            "systemInstruction": {"parts": [{"text": req.system}]},
            "contents": [{"role": "user", "parts": [
                {"inline_data": {"mime_type": req.document.mime,
                                 "data": base64.b64encode(req.document.data).decode()}},
                {"text": req.prompt}]}],
            "generationConfig": {"temperature": req.temperature,
                                 "responseMimeType": "application/json",
                                 "responseJsonSchema": req.schema}}
        http = urllib.request.Request(
            f"https://generativelanguage.googleapis.com/v1beta/models/{req.model}:generateContent",
            json.dumps(body).encode(), {"x-goog-api-key": self.key, "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(http, timeout=self.timeout) as r:
                payload = json.load(r)
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")
            if e.code == 429:
                raise RateLimited(daily="PerDay" in detail) from None
            if e.code in (500, 503):
                raise RateLimited() from None  # capacity error (ADR 0002): back off and retry
            raise
        return json.loads(payload["candidates"][0]["content"]["parts"][0]["text"])


def resolve_model(model: str) -> str:
    """Accept a pin alias ("flash", "flash_lite") or a pinned model name; refuse anything else."""
    name = PINS.get(model, model)
    if name not in ALLOWED_MODELS:
        raise ModelNotAllowed(model)
    return name


def synthetic_hashes(manifest: dict) -> frozenset[str]:
    """Document hashes listed in a synthetic manifest (hermes.synthetic.generate's output)."""
    return frozenset(f["sha256"] for f in manifest["files"] if "sha256" in f)


class ModelClient:
    def __init__(self, backend: Backend, cache=None, manifest_hashes=frozenset(), sleep=time.sleep,
                 data_mode: str | None = None):
        self.backend, self.cache = backend, cache if cache is not None else MemoryCache()
        self.manifest_hashes, self.sleep = frozenset(manifest_hashes), sleep
        self.data_mode = data_mode or os.environ.get("HERMES_DATA_MODE", "synthetic")
        self.hits = self.misses = 0

    @property
    def stats(self) -> dict:
        return {"hits": self.hits, "misses": self.misses}

    def call(self, task: str, model: str, prompt_version: str, system: str, prompt: str,
             document: Document, schema: dict) -> Result:
        """Run one task on one document. Returns Result("ok", data) or Result("review", reason)."""
        name, h = resolve_model(model), document.sha256
        if self.data_mode == "synthetic" and h not in self.manifest_hashes:
            log.warning("refused non-synthetic document task=%s doc=%s", task, h[:12])
            raise DataModeRefused(f"document {h[:12]} is not in the synthetic manifest")
        key = hashlib.sha256(f"{task}|{name}|{prompt_version}|{h}".encode()).hexdigest()
        if (hit := self.cache.get(key)) is not None:
            self.hits += 1
            log.info("cache hit task=%s model=%s doc=%s", task, name, h[:12])
            return Result("ok", hit, model=name, cached=True)
        self.misses += 1
        temp = 0.0 if task.startswith(ZERO_TEMPERATURE_TASKS) else 0.2
        req = Request(task, name, system, prompt, document, schema, temp)
        for attempt in (1, 2):  # one retry on an invalid response
            try:
                data = self._generate(req)
            except RateLimited as e:
                log.warning("quota unavailable task=%s model=%s daily=%s", task, name, e.daily)
                return Result("review", reason=str(e), model=name)
            if not check_schema(data, schema):
                self.cache.put(key, task, name, prompt_version, h, data)
                return Result("ok", data, model=name)
            log.info("invalid response task=%s model=%s attempt=%d", task, name, attempt)
        return Result("review", reason="schema validation failed twice", model=name)

    def _generate(self, req: Request) -> dict:
        for delay in (*RETRY_AFTER, None):
            try:
                return self.backend.generate(req)
            except RateLimited as e:
                if e.daily or delay is None:
                    raise RateLimited(daily=e.daily) from None
                self.sleep(delay)


SKIP_SIGNATURE = "skip_thought_signature_validator"


def gemini_tool_model(api_key: str, name: str | None, limit_exc: type[Exception], timeout: float = 60):
    """The real model: Gemini generateContent over REST on the pinned Flash model, one call per turn.
    ponytail: no cache or backoff here; the loop retries failed events itself."""
    import httpx

    name = name or PINS["flash"]

    def model(system: str, msgs: list[dict], decls: list[dict]) -> dict:
        contents = []
        for m in msgs:
            if m["role"] == "tool":  # the answers to one turn's calls go back together, in one user turn
                part = {"functionResponse": {"name": m["name"], "response": m["result"]}}
                if contents and contents[-1]["role"] == "user" and "functionResponse" in contents[-1]["parts"][0]:
                    contents[-1]["parts"].append(part)
                else:
                    contents.append({"role": "user", "parts": [part]})
            else:
                parts = [{"text": m["text"]}] if m.get("text") else []
                # Gemini 3 refuses a replayed call without its thought signature (found on the first live run)
                # a reply cached before signatures were kept has none: Google's documented dummy value stands in
                parts += [{"functionCall": {"name": c["name"], "args": c.get("args") or {}},
                           **({"thoughtSignature": c.get("sig") or SKIP_SIGNATURE} if n == 0 else
                              ({"thoughtSignature": c["sig"]} if c.get("sig") else {}))}
                          for n, c in enumerate(m.get("calls", []))]
                contents.append({"role": m["role"], "parts": parts})
        r = httpx.post(f"https://generativelanguage.googleapis.com/v1beta/models/{name}:generateContent",
                       headers={"x-goog-api-key": api_key}, timeout=timeout,
                       json={"systemInstruction": {"parts": [{"text": system}]}, "contents": contents,
                             "tools": [{"functionDeclarations": decls}]})
        if r.status_code == 429:
            raise limit_exc(r.text)
        if r.is_error:
            logging.getLogger("hermes.llm").warning("gemini %s: %s", r.status_code, r.text[:500])
        r.raise_for_status()
        body = r.json()
        parts = body["candidates"][0]["content"].get("parts", [])
        use = body.get("usageMetadata", {})
        return {"calls": [{"name": p["functionCall"]["name"], "args": p["functionCall"].get("args", {}),
                           "sig": p.get("thoughtSignature")} for p in parts if "functionCall" in p],
                "text": "".join(p.get("text", "") for p in parts),
                "tokens_in": use.get("promptTokenCount"), "tokens_out": use.get("candidatesTokenCount")}

    model.name = name
    return model
