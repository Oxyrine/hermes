"""Manual live run (ticket 28): the paced, cached plumbing for real Gemini calls, and the scenario
runs that compare the Gemini loop with real extraction against the scripted runner.

`uv run python -m hermes.live all` runs the scenarios and the evaluation (hermes.evaluation) and
writes the dated report. Never part of CI: the tests marked `live` are excluded by default, and
nothing here is imported by the app. The key is read from the environment or the git-ignored .env
and is never printed. Every model call goes through the response cache, so a second run is free.
"""

import hashlib
import json
import logging
import os
import re
import time
from pathlib import Path

from hermes.agent import LOOP_PROMPT_VERSION, ModelLimit, gemini_model
from hermes.llm import (
    PINS,
    Backend,
    Document,
    FakeModel,
    GeminiBackend,
    ModelClient,
    RateLimited,
    synthetic_hashes,
)

log = logging.getLogger("hermes.live")
CACHE_FILE = Path("storage/live-cache/model_cache.jsonl")
# Seconds between calls to one model. Google does not publish the free-tier limits (ADR 0002); a 429 on
# 2026-11-15 named 15 requests a minute for Flash-Lite and 20 a day for Flash, so stay under those.
GAP = {PINS["flash"]: 8.0, PINS["flash_lite"]: 6.5}
TIMEOUT = 180  # seconds: the pinned Flash took 50 s to say one word on 2026-11-15 (ADR 0002 warned of it)
BACKOFF = (5, 20, 60, 120)  # after a 429 or a capacity error; the daily limit is never retried
UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
STAMP = re.compile(r"\d{4}-\d\d-\d\d[T ]\d\d:\d\d:\d\d(?:\.\d+)?(?:Z|[+-]\d\d:?\d\d)?")


def load_env(path: str = ".env", keys=("GEMINI_API_KEY",)) -> None:
    """Put the named keys of a git-ignored .env into the environment (never overriding, never printing).
    Only the key: a DATABASE_URL in there must never point this run's database resets at a real database."""
    p = Path(path)
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            k, sep, v = line.partition("=")
            if sep and k.strip() in keys:
                os.environ.setdefault(k.strip(), v.strip().strip("\"'"))


class FileCache:
    """The response cache as a JSON-lines file: survives the database being reset between runs."""

    def __init__(self, path: Path = CACHE_FILE):
        self.path, self.rows = Path(path), {}
        if self.path.exists():
            for line in self.path.read_text(encoding="utf-8").splitlines():
                row = json.loads(line)
                self.rows[row["key"]] = row["response"]

    def get(self, key: str):
        return self.rows.get(key)

    def put(self, key, task, model, prompt_version, doc_hash, response):
        if key not in self.rows:
            self.rows[key] = response
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"key": key, "task": task, "model": model, "prompt": prompt_version,
                                    "doc": doc_hash[:12], "response": response}) + "\n")


class Pacer:
    """Keeps each model under its per-minute limit and counts the calls that really go out."""

    def __init__(self, gap=GAP, sleep=time.sleep, clock=time.monotonic):
        self.gap, self.sleep, self.clock, self.last, self.api_calls = gap, sleep, clock, {}, 0

    def wait(self, model: str) -> None:
        due = self.last.get(model, float("-inf")) + self.gap.get(model, 10.0)
        if (late := due - self.clock()) > 0:
            self.sleep(late)
        self.last[model] = self.clock()
        self.api_calls += 1


class PacedBackend:
    """A ModelClient backend wrapper: pace every real call; a timeout counts as a capacity error."""

    def __init__(self, inner: Backend, pacer: Pacer):
        self.inner, self.pacer = inner, pacer

    def generate(self, req) -> dict:
        self.pacer.wait(req.model)
        try:
            return self.inner.generate(req)
        except OSError as e:  # a timeout or a dropped connection is a capacity error ...
            if getattr(e, "code", None) is not None:
                raise  # ... but a refused request (an HTTP status) is a bug
            raise RateLimited() from None


def _canon(obj) -> tuple[str, list[str]]:
    """The request as text with every id and timestamp made stable, so a rerun on a fresh database
    asks the same question. Returns (text, the ids in order of appearance)."""
    ids: list[str] = []

    def rep(m):
        if m[0] not in ids:
            ids.append(m[0])
        return f"<id:{ids.index(m[0])}>"

    text = STAMP.sub("<ts>", json.dumps(obj, sort_keys=True, default=str))
    return UUID.sub(rep, text), ids


class LoopModel:
    """The loop's model, cached and paced: `inner` is hermes.agent.gemini_model(...)."""

    def __init__(self, inner, cache, pacer: Pacer, sleep=time.sleep):
        self.inner, self.cache, self.pacer, self.sleep = inner, cache, pacer, sleep
        self.name, self.hits, self.seen = inner.name, 0, []  # seen: every tool name the model asked for

    def __call__(self, system, msgs, decls) -> dict:
        text, ids = _canon([system, msgs, decls])
        key = hashlib.sha256(f"loop|{self.name}|{LOOP_PROMPT_VERSION}|{text}".encode()).hexdigest()
        if (hit := self.cache.get(key)) is not None:
            self.hits += 1
            reply = json.loads(re.sub(r"<id:(\d+)>", lambda m: ids[int(m[1])], json.dumps(hit)))
        else:
            reply = self._ask(system, msgs, decls)
            stored = json.dumps(reply)
            for n, i in enumerate(ids):
                stored = stored.replace(i, f"<id:{n}>")
            self.cache.put(key, "loop", self.name, LOOP_PROMPT_VERSION, key, json.loads(stored))
        self.seen += [c["name"] for c in reply["calls"]]
        return reply

    def _ask(self, system, msgs, decls) -> dict:
        import httpx
        for delay in (*BACKOFF, None):
            self.pacer.wait(self.name)
            try:
                return self.inner(system, msgs, decls)
            except ModelLimit as e:
                why = "429 " + " ".join(str(e).split())[:300]
                if "PerDay" in str(e) or delay is None:
                    raise
            except (httpx.TimeoutException, httpx.TransportError) as e:
                why = type(e).__name__
                if delay is None:
                    raise
            except httpx.HTTPStatusError as e:
                why = f"HTTP {e.response.status_code}"
                if e.response.status_code not in (500, 503) or delay is None:
                    raise
            log.warning("loop model unavailable (%s), backing off %ss", why, delay)
            self.sleep(delay)


def email_document(root: Path, path: str) -> Document:
    """A thread as the fixture adapter hands it over: the ground-truth label stripped. Never send the label."""
    e = json.loads((root / path).read_text(encoding="utf-8"))
    return Document(json.dumps({k: v for k, v in e.items() if k != "label"}).encode(), "text/plain")


def synthetic_set(root: Path, manifest: dict) -> frozenset[str]:
    """What the synthetic-only guard lets through: the manifest's files and the label-free threads."""
    return frozenset(synthetic_hashes(manifest)) | {
        email_document(root, f["path"]).sha256 for f in manifest["files"] if f["kind"] == "email"}


def truth_model(root: Path, manifest: dict) -> FakeModel:
    """A model that reads the synthetic set perfectly, by document hash: the scripted baseline."""
    from hermes.extraction import FIELDS

    truth = {}
    for f in manifest["files"]:
        stem = f["path"].removesuffix(".pdf").removesuffix(".json")
        if f["kind"] in FIELDS:
            t = json.loads((root / f"{stem}.truth.json").read_text(encoding="utf-8"))
            t.pop("injection", None)
            truth[("classify", f["sha256"])] = {"doc_type": f["kind"], "confidence": 0.95}
            truth[("extract", f["sha256"])] = t | {"confidence": 0.97}
            truth[("mismatch_note", f["sha256"])] = {"note": "This document differs from the invoice."}
        elif f["kind"] == "contract":
            t = json.loads((root / f"{stem}.truth.json").read_text(encoding="utf-8"))
            if t["payment_days"]:
                truth[("extract.contract_terms", f["sha256"])] = {
                    k: t[k] for k in ("payment_days", "from_event", "clause_quote", "page")} | {"confidence": 0.95}
            else:
                truth[("extract.contract_terms", f["sha256"])] = {"confidence": 0.9}
        elif f["kind"] == "email":
            e = json.loads((root / f["path"]).read_text(encoding="utf-8"))
            lab, ref = e["label"], e["messages"][0]["subject"].split()[-1]
            truth[("detect.objection", email_document(root, f["path"]).sha256)] = {
                "is_objection": lab["is_objection"], "confidence": 0.95 if lab["is_objection"] else 0.3,
                "invoice_refs": [ref], **({"raised_on": lab["raised_on"], "quote": lab["quote"]}
                                          if lab["is_objection"] else {})}
    return FakeModel(truth)


class Recorder:
    """The client for text derived from the synthetic set (a letter's engine values), which no manifest
    lists: the database it comes from is synthetic-only, so its hash joins the guard's list. Keeps every
    (task, document, result) so raw drafts can be checked."""

    def __init__(self, client: ModelClient):
        self.client, self.rows = client, []

    def call(self, task, model, prompt_version, system, prompt, document, schema):
        self.client.manifest_hashes |= {document.sha256}
        res = self.client.call(task, model, prompt_version, system, prompt, document, schema)
        self.rows.append((task, document, res))
        return res


class Live:
    """The live pieces for one run: cache, pacer, the Gemini-backed client and the loop model."""

    def __init__(self, root: Path, manifest: dict, cache=None, pacer=None):
        self.cache, self.pacer = cache or FileCache(), pacer or Pacer()
        self.hashes = set(synthetic_set(root, manifest))
        self.client = ModelClient(PacedBackend(GeminiBackend(timeout=TIMEOUT), self.pacer), cache=self.cache,
                                  manifest_hashes=self.hashes)  # data_mode stays "synthetic"
        self.loop = LoopModel(gemini_model(os.environ["GEMINI_API_KEY"], timeout=TIMEOUT), self.cache, self.pacer)

    def stats(self) -> dict:
        return {"api_calls": self.pacer.api_calls, "cache_hits": self.client.hits + self.loop.hits,
                "cache_misses": self.client.misses}


def main(argv=None) -> int:
    """`python -m hermes.live [scenarios] [eval] [injection] [docs] [--report PATH] [--expect-no-calls]`."""
    import argparse
    import tempfile
    from datetime import date

    from hermes import evaluation, extraction, facts, letter
    from hermes.live_scenarios import run_injection, run_scenarios
    from hermes.synthetic import generate

    ap = argparse.ArgumentParser(prog="hermes.live")
    ap.add_argument("parts", nargs="*", default=["scenarios", "eval", "injection"])
    ap.add_argument("--report")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--expect-no-calls", action="store_true")
    ap.add_argument("--flash-as-lite", action="store_true",
                    help="serve the Flash role with Flash-Lite (when Flash's free daily quota is spent); labelled in the report")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(message)s")
    load_env()
    assert os.environ.get("HERMES_DATA_MODE", "synthetic") == "synthetic", "the live run is synthetic-only"
    flash = PINS["flash"]
    if args.flash_as_lite:
        PINS["flash"] = PINS["flash_lite"]  # still one of the two pinned models; cache keys carry the name
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "syn"
        manifest = generate(root)
        live, out = Live(root, manifest), {}
        import pixeltable_pgserver as pgserver  # always a throwaway database: the stages reset it
        server = pgserver.get_server(Path(tmp) / "pg")
        dsn = server.get_uri()
        try:
            for part in args.parts:
                print(f"== {part}", flush=True)
                out[part] = {"scenarios": lambda: run_scenarios(dsn, root, manifest, live),
                             "eval": lambda: evaluation.run_evaluation(dsn, root, manifest, live, args.limit),
                             "injection": lambda: run_injection(dsn, root, manifest, live),
                             "docs": lambda: evaluation.read_documents(  # only the cheap Flash-Lite reads
                                 root, manifest, extraction.Reader(live.client), args.limit)}[part]()
                Path(f"storage/live-{part}.json").write_text(json.dumps(out[part], indent=1, default=str),
                                                             encoding="utf-8")
                print(f"   results in storage/live-{part}.json", flush=True)
        finally:
            server.cleanup()
    stats = live.stats()
    print(f"model calls made: {stats['api_calls']}; cache hits: {stats['cache_hits']}; "
          f"misses: {stats['cache_misses']}", flush=True)
    if args.report and {"scenarios", "eval", "injection"} <= out.keys():
        versions = {"extraction and classification prompts": extraction.PROMPT_VERSION,
                    "objection and contract-term prompts": facts.PROMPT_VERSION,
                    "letter prompt": letter.PROMPT_VERSION, "agent loop prompt": LOOP_PROMPT_VERSION}
        models = {"Flash (pinned)": flash, "Flash-Lite (pinned)": PINS["flash_lite"],
                  "Model that served the Flash role in this run": PINS["flash"]}
        text = evaluation.render(date.today().isoformat(), models, versions, out["scenarios"], out["eval"],
                                 out["injection"], stats, substituted=args.flash_as_lite)
        Path(args.report).parent.mkdir(parents=True, exist_ok=True)
        Path(args.report).write_text(text, encoding="utf-8")
        print("report written", args.report)
    return 1 if args.expect_no_calls and stats["api_calls"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
