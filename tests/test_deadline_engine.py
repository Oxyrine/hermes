import pytest

from hermes.engines.deadline import run


def res(delivery="2026-08-01", days=None, ob=None, **kw):
    return run({"delivery": delivery, "written_days": days, "objection": ob, **kw})


def test_no_term_15_days():
    assert res()["result"]["due"] == "2026-08-16"


def test_term_30_and_cap_45():
    assert res(days=30)["result"]["due"] == "2026-08-31"
    out = res(days=60)
    assert out["result"]["due"] == "2026-09-15"
    assert any("capped" in r for r in out["reasons"])


def test_spec_example():
    r = res(days=45)["result"]
    assert (r["acceptance"], r["due"], r["interest_from"]) == (
        "2026-08-01", "2026-09-15", "2026-09-16")


def test_objection_removed_moves_acceptance():
    r = res(ob={"raised_on": "2026-08-11", "removed_on": "2026-08-26"})["result"]
    assert r["acceptance"] == "2026-08-26" and r["basis"] == "objection_removed"


def test_late_objection_ignored():
    r = res(ob={"raised_on": "2026-08-21", "removed_on": None})["result"]
    assert r["acceptance"] == "2026-08-01" and r["basis"] == "actual_or_deemed"
    r = res(ob={"raised_on": "2026-08-16", "removed_on": None})["result"]  # day 15: in time
    assert r["status"] == "open_objection"


def test_open_objection():
    out = res(ob={"raised_on": "2026-08-05", "removed_on": None})
    r = out["result"]
    assert r["status"] == "open_objection" and r["due"] is None and r["interest_from"] is None
    assert r["reason"] == "acceptance not yet fixed" and "acceptance not yet fixed" in out["reasons"]


def test_instalments_use_last_and_flag():
    out = res(instalment_dates=["2026-07-01", "2026-08-01", "2026-07-15"], delivery="2026-07-01")
    assert out["result"]["acceptance"] == "2026-08-01"
    assert any("instalments" in r for r in out["reasons"])


def test_reasons_name_day_count_and_envelope():
    out = res()
    assert set(out) == {"engine", "rule_version", "input_hash", "result", "reasons"}
    assert "awaiting legal review" in " ".join(out["reasons"]).lower()
    assert res() == res()


@pytest.mark.parametrize("bad", [-1, True, 1.5, "30"])
def test_bad_term_rejected(bad):
    with pytest.raises(ValueError):
        res(days=bad)
