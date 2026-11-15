import logging
from pathlib import Path

import pytest

from hermes import llm
from hermes.llm import Document, FakeModel, ModelClient, ModelNotAllowed, RateLimited

SCHEMA = {"type": "object", "required": ["a"], "properties": {"a": {"type": "string"}}}
DOC = Document(b"SECRET-INVOICE-TEXT")
SYNTH = {DOC.sha256}


def client(truth, **kw):
    fake = FakeModel(truth)
    kw.setdefault("manifest_hashes", SYNTH)
    kw.setdefault("sleep", lambda s: None)
    return fake, ModelClient(fake, **kw)


def call(c, model="flash_lite", task="extract.invoice", doc=DOC):
    return c.call(task, model, "v1", "sys", "go", doc, SCHEMA)


def test_only_pinned_models_selectable():
    _fake, c = client({DOC.sha256: {"a": "x"}})
    assert call(c, "flash").model == llm.PINS["flash"]
    assert call(c, llm.PINS["flash_lite"]).status == "ok"
    for bad in ("gemini-3.1-pro", "gemini-3.7-flash", "pro"):
        with pytest.raises(ModelNotAllowed):
            call(c, bad)


def test_invalid_response_retried_once_then_review():
    fake, c = client({DOC.sha256: [{"b": 1}, {"a": "ok"}]})
    assert call(c).data == {"a": "ok"} and len(fake.calls) == 2
    fake, c = client({DOC.sha256: [{"b": 1}, {"b": 2}]})
    r = call(c)
    assert r.status == "review" and len(fake.calls) == 2


def test_temperature_zero_for_extraction_and_detection_and_document_is_a_file():
    fake, c = client({DOC.sha256: {"a": "x"}})
    for t in ("classify.doc", "extract.invoice", "detect.objection"):
        call(c, task=t)
    call(c, "flash", task="draft.letter")
    assert [r.temperature for r in fake.calls] == [0, 0, 0, 0.2]
    assert all(r.document.data == DOC.data and b"SECRET" not in r.system.encode() for r in fake.calls)


def test_cache_hit_makes_no_call_and_counts():
    fake, c = client({DOC.sha256: {"a": "x"}})
    call(c), call(c)
    assert len(fake.calls) == 1 and c.stats == {"hits": 1, "misses": 1}
    assert call(c).cached
    call(c, "flash")  # other model: miss
    assert c.stats == {"hits": 2, "misses": 2}


def test_pg_cache_survives_new_client(dsn):
    import psycopg
    with psycopg.connect(dsn, autocommit=True) as conn:
        _fake, c = client({DOC.sha256: {"a": "x"}}, cache=llm.PgCache(conn))
        call(c)
        fake2, c2 = client({}, cache=llm.PgCache(conn))
        assert call(c2).data == {"a": "x"} and not fake2.calls


def test_rate_limit_backs_off_and_retries():
    sleeps = []
    _fake, c = client({DOC.sha256: [RateLimited(), RateLimited(), {"a": "x"}]}, sleep=sleeps.append)
    assert call(c).status == "ok" and sleeps == [2, 8]


def test_exhausted_daily_limit_routes_to_review_without_raising_or_backoff():
    sleeps = []
    fake, c = client({DOC.sha256: RateLimited(daily=True)}, sleep=sleeps.append)
    r = call(c)
    assert r.status == "review" and "daily" in r.reason and not sleeps and len(fake.calls) == 1
    assert c.cache.rows == {}


def test_synthetic_guard_refuses_before_call_and_logs_no_content(caplog):
    other = Document(b"REAL-CUSTOMER-DOC")
    fake, c = client({other.sha256: {"a": "x"}, DOC.sha256: {"a": "x"}})
    with caplog.at_level(logging.DEBUG, logger="hermes.llm"), pytest.raises(llm.DataModeRefused):
        call(c, doc=other)
    assert not fake.calls
    call(c)  # allowed doc, logs too
    text = caplog.text
    assert "refused" in text and "REAL-CUSTOMER" not in text and "SECRET" not in text
    # explicit non-synthetic mode lets it through
    fake, c = client({other.sha256: {"a": "x"}}, data_mode="live")
    assert call(c, doc=other).status == "ok"


def test_default_mode_is_synthetic(monkeypatch):
    monkeypatch.delenv("HERMES_DATA_MODE", raising=False)
    assert ModelClient(FakeModel({})).data_mode == "synthetic"


def test_synthetic_hashes_from_generated_manifest(tmp_path):
    from hermes.synthetic import generate
    hashes = llm.synthetic_hashes(generate(tmp_path))
    pdf = next(tmp_path.glob("docs/*/invoice.pdf")).read_bytes()
    assert Document(pdf).sha256 in hashes


def test_no_other_code_calls_a_model():
    src = Path(llm.__file__).parent
    offenders = [p.name for p in src.rglob("*.py")
                 if p.name != "llm.py" and "generativelanguage" in p.read_text(encoding="utf-8")]
    assert offenders == []
