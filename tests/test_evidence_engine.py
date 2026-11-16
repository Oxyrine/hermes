import pytest

from hermes.engines.evidence import run


def score(signals, as_of="2026-02-14"):
    return run({"as_of": as_of, "signals": signals})


def sig(t, **kw):
    return {"type": t, "source": f"src:{t}", **kw}


@pytest.mark.parametrize(
    "as_of,pts", [("2026-02-13", 0), ("2026-02-14", 12), ("2026-02-15", 12)]
)
def test_deemed_acceptance_boundary(as_of, pts):
    out = score([sig("ims_no_action", gstr2b_generated="2026-02-14")], as_of)
    assert out["result"]["score"] == pts
    assert out["result"]["contributions"][0]["points"] == pts


def test_full_evidence_band_a_and_clamp():
    allpos = [sig(t) for t in (
        "irn_valid_matching", "ewb_matching", "grn_matching", "po_matching",
        "ims_accepted", "buyer_email_ack", "part_payment")]
    r = score(allpos)["result"]
    assert (r["score"], r["band"], r["needs_review"]) == (95, "A", False)
    assert score(allpos + [sig("ims_accepted")])["result"]["score"] == 100


def test_hard_flag_forces_review_and_floor():
    r = score([sig("ims_rejected")])["result"]
    assert r["score"] == 0 and r["band"] == "D"
    assert r["hard_flags"] == ["ims_rejected"] and r["needs_review"]
    r = score([sig(t) for t in ("irn_valid_matching", "ims_accepted", "grn_matching",
                                "ewb_matching", "po_matching", "written_objection_15d")])["result"]
    assert r["score"] == 60 and r["band"] == "B" and r["needs_review"]


@pytest.mark.parametrize("pts,band", [(79, "B"), (60, "B"), (59, "C"), (40, "C"), (39, "D")])
def test_band_edges(pts, band):
    from hermes.engines.evidence.engine import _band

    assert _band(pts) == band


def test_envelope_and_unknown():
    out = score([sig("debit_note")])
    assert out["rule_version"] == "1.2.0" and len(out["input_hash"]) == 64
    assert out["result"]["contributions"][0]["source"] == "src:debit_note"
    with pytest.raises(ValueError):
        score([sig("nope")])
