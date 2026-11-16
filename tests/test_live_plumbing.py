"""Ticket 28, offline: the loop's model-reading tools on a fake reader and a stubbed loop model, and the
pacing and cache plumbing of the manual live run. No key, no network."""

import urllib.error

import pytest
from fastapi.testclient import TestClient

from hermes import live
from hermes.agent import ALLOWED, DECLARATIONS, READS, GeminiAgent
from hermes.api import create_app
from hermes.dispatcher import drain
from hermes.llm import ModelClient, RateLimited, synthetic_hashes
from test_adapters import conn, invoice_id, pull, root, world  # noqa: F401
from test_classify_extract import INV, fake_for, prepare, reader_for, state, upload
from test_seeded_invoice_api import SECRET, login

U1, U2 = "11111111-2222-3333-4444-555555555555", "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


def test_the_four_reading_tools_and_move_state_are_on_the_allowlist():
    assert set(READS) == {"classify_document", "extract_fields", "detect_objection", "read_contract_terms"}
    assert {*READS, "move_state"} <= ALLOWED == {d["name"] for d in DECLARATIONS}


@pytest.fixture
def client(world):  # noqa: F811
    return TestClient(create_app(world, secret=SECRET, env="development"))


def scripted_loop(*steps):
    """A loop model that answers each turn with the next list of (tool, args) calls, then stops."""
    it = iter(steps)
    return lambda system, msgs, decls: {"calls": [{"name": n, "args": a} for n, a in next(it, [])]}


def test_loop_reads_documents_through_tools_and_moves_the_invoice(client, conn, root):  # noqa: F811
    prepare(client, conn, root, INV, None)
    iid = upload(client, root, INV)
    reader = reader_for(root, fake_for(root, INV))
    seen = []

    def model(system, msgs, decls):
        seen.extend(m for m in msgs if m.get("name") == "classify_document")
        names = [m.get("name") for m in msgs if m["role"] == "tool"]
        if not names:
            return {"calls": [{"name": "classify_document", "args": {}}, {"name": "extract_fields", "args": {}}]}
        if "move_state" not in names:
            return {"calls": [{"name": "move_state", "args": {"to": "verified"}},
                              {"name": "move_state", "args": {"to": "financeable"}}]}
        return {"calls": []}

    model.name = "stub"
    drain(conn.info.dsn, SECRET, client, reader, model)
    assert state(client, iid) == "verified"  # trader supplier: manual_review keeps it from financeable
    assert {m["result"]["doc_type"] for m in seen if "doc_type" in m["result"]} == {"invoice", "purchase_order", "goods_receipt_note"}
    runs = conn.execute("SELECT runner FROM agent_run").fetchall()
    assert runs and all(r[0] == "gemini" for r in runs)


def test_a_reading_tool_names_no_document_and_refuses_the_wrong_kind(client, conn, root):  # noqa: F811
    prepare(client, conn, root, INV, None)
    iid = upload(client, root, INV, ("invoice",))
    h = login(client, "agent@lender-a.example")
    agent = GeminiAgent(client, h["Authorization"].split()[1], scripted_loop(), "stub",
                        reader=reader_for(root, fake_for(root, INV, kinds=("invoice",))))
    did = conn.execute("SELECT id::text FROM document WHERE invoice_id=%s", (iid,)).fetchone()[0]
    agent.event = {"invoice_id": iid, "kind": "document.ingested", "payload": {"document_id": did, "doc_type": "invoice"}}
    assert "doc_type" in agent.tool(iid, "classify_document", {"document_id": "someone-elses"})
    assert "not an email" in agent.tool(iid, "detect_objection", {})["error"]
    assert "not a contract" in agent.tool(iid, "read_contract_terms", {})["error"]
    agent.event = {"invoice_id": None, "kind": "bank_rate.changed", "payload": {}}
    assert "no document" in agent.tool(iid, "extract_fields", {})["error"]


def test_canonical_form_makes_a_rerun_on_a_fresh_database_ask_the_same_question():
    a = live._canon([{"id": U1, "at": "2026-11-15T10:00:00.123+00:00", "x": [U1, U2]}])
    b = live._canon([{"id": U2, "at": "2026-11-16 09:30:01+00:00", "x": [U2, U1]}])
    assert a[0] == b[0] and a[1] == [U1, U2] and b[1] == [U2, U1]


class Stub:
    name = "gemini-3.8-flash"

    def __init__(self):
        self.calls = 0

    def __call__(self, system, msgs, decls):
        self.calls += 1
        return {"calls": [{"name": "read_invoice", "args": {"id": msgs[0]["text"]}}], "text": "", "tokens_in": 3}


def test_loop_model_caches_across_databases_and_maps_ids_back(tmp_path):
    pacer, stub = live.Pacer(sleep=lambda s: None), Stub()
    cache = live.FileCache(tmp_path / "c.jsonl")
    first = live.LoopModel(stub, cache, pacer)("sys", [{"role": "user", "text": U1}], [])
    again = live.LoopModel(stub, live.FileCache(tmp_path / "c.jsonl"), pacer)  # a new process
    second = again("sys", [{"role": "user", "text": U2}], [])
    assert stub.calls == 1 and pacer.api_calls == 1 and again.hits == 1
    assert first["calls"][0]["args"]["id"] == U1 and second["calls"][0]["args"]["id"] == U2  # ids follow the run
    assert again.seen == ["read_invoice"]


def test_pacer_keeps_each_model_under_its_gap():
    now, slept = [100.0], []
    pacer = live.Pacer({"m": 8.0}, sleep=lambda s: (slept.append(s), now.__setitem__(0, now[0] + s)),
                       clock=lambda: now[0])
    for _ in range(3):
        pacer.wait("m")
    pacer.wait("other")
    assert slept == [8.0, 8.0] and pacer.api_calls == 4


def test_loop_model_backs_off_on_a_per_minute_limit_but_not_on_the_daily_one(tmp_path):
    from hermes.agent import ModelLimit

    errors = [ModelLimit("429 per minute"), ModelLimit("429 per minute")]

    class Flaky(Stub):
        def __call__(self, *a):
            if errors:
                raise errors.pop(0)
            return super().__call__(*a)

    waits = []
    m = live.LoopModel(Flaky(), live.FileCache(tmp_path / "c.jsonl"), live.Pacer(sleep=lambda s: None),
                       sleep=waits.append)
    assert m("s", [{"role": "user", "text": "t"}], [])["calls"] and waits == [5, 20]

    class Daily(Stub):
        def __call__(self, *a):
            raise ModelLimit("quota exceeded PerDay")

    with pytest.raises(ModelLimit):
        live.LoopModel(Daily(), live.FileCache(tmp_path / "d.jsonl"), live.Pacer(sleep=lambda s: None),
                       sleep=waits.append)("s", [{"role": "user", "text": "t"}], [])
    assert waits == [5, 20]  # no wait for the daily limit


def test_a_refused_request_is_a_bug_but_a_timeout_is_a_capacity_error():
    class Raises:
        def __init__(self, exc):
            self.exc = exc

        def generate(self, req):
            raise self.exc

    pacer = live.Pacer(sleep=lambda s: None)
    bad = urllib.error.HTTPError("u", 400, "Bad Request", {}, None)
    with pytest.raises(urllib.error.HTTPError):
        live.PacedBackend(Raises(bad), pacer).generate(type("R", (), {"model": "m"}))
    with pytest.raises(RateLimited):
        live.PacedBackend(Raises(TimeoutError()), pacer).generate(type("R", (), {"model": "m"}))


def test_file_cache_serves_the_model_client_and_the_guard_stays_on(tmp_path, root):  # noqa: F811
    from hermes.llm import DataModeRefused, Document, FakeModel

    doc = Document(b"x")
    fake = FakeModel({doc.sha256: {"ok": True}})
    schema = {"type": "object"}
    client = ModelClient(fake, cache=live.FileCache(tmp_path / "c.jsonl"), manifest_hashes={doc.sha256})
    client.call("extract", "flash", "v", "s", "p", doc, schema)
    again = ModelClient(fake, cache=live.FileCache(tmp_path / "c.jsonl"), manifest_hashes={doc.sha256})
    assert again.call("extract", "flash", "v", "s", "p", doc, schema).cached and len(fake.calls) == 1
    with pytest.raises(DataModeRefused):
        ModelClient(fake, manifest_hashes=synthetic_hashes(root[1])).call("extract", "flash", "v", "s", "p", doc, schema)


def test_truth_model_reads_every_synthetic_document(root):  # noqa: F811
    model = live.truth_model(*root)
    assert {t for t, _ in model.truth} == {"classify", "extract", "mismatch_note", "detect.objection",
                                           "extract.contract_terms"}
    assert len([k for k in model.truth if k[0] == "detect.objection"]) == 20
