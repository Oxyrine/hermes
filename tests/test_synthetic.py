import base64
import hashlib
import hmac
import json
import re
from collections import Counter
from pathlib import Path

import pytest

from hermes.synthetic import generate, is_valid_gstin
from hermes.synthetic.generate import QR_TEST_KEY


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    root = tmp_path_factory.mktemp("syn")
    return root, generate(root, seed=42)


def load(root, rel):
    return json.loads((Path(root) / rel).read_text())


def text_layer(path):
    return b" ".join(re.findall(rb"\((.*?)\) Tj", Path(path).read_bytes())).decode()


def test_deterministic(world, tmp_path):
    root, m = world
    m2 = generate(tmp_path, seed=42)
    assert m == m2
    for f in m["files"]:
        assert (root / f["path"]).read_bytes() == (tmp_path / f["path"]).read_bytes()
    assert generate(tmp_path / "other", seed=7)["files"] != m["files"]


def test_manifest_hashes_and_counts(world):
    root, m = world
    assert m["counts"] == {"suppliers": 3, "buyers": 4, "invoices": 30, "emails": 20}
    for f in m["files"]:
        assert hashlib.sha256((root / f["path"]).read_bytes()).hexdigest() == f["sha256"]


def test_gstins_valid(world):
    _, m = world
    assert all(is_valid_gstin(p["gstin"]) for p in m["suppliers"] + m["buyers"])


def test_truth_quotes_in_text_layer_and_arithmetic(world):
    root, m = world
    truths = [f for f in m["files"] if f["kind"] == "ground_truth" and "/" in f["path"]
              and not f["path"].startswith("bank/")]
    assert truths
    for f in truths:
        t = load(root, f["path"])
        text = text_layer((root / f["path"]).with_name(Path(f["path"]).name.replace(".truth.json", ".pdf")))
        for q in t["sources"].values():
            assert q["page"] == 1 and q["quote"] in text, (f["path"], q)
        if t["doc_type"] == "invoice":
            assert sum(i["amount"] for i in t["line_items"]) == pytest.approx(t["taxable_value"])
            assert t["taxable_value"] + t["gst_amount"] == pytest.approx(t["total"], abs=0.01)
            assert is_valid_gstin(t["supplier_gstin"]) and is_valid_gstin(t["buyer_gstin"])
            head, body, sig = t["qr_payload"].split(".")
            good = hmac.new(QR_TEST_KEY, f"{head}.{body}".encode(), hashlib.sha256).digest()
            assert base64.urlsafe_b64decode(sig + "==") == good


def test_scenarios_and_e2e(world):
    _, m = world
    assert len(m["invoices"]) == 30
    assert all(m["e2e_scenarios"][f"{n}"] for n in m["e2e_scenarios"]) and len(m["e2e_scenarios"]) == 6


def test_emails(world):
    root, m = world
    labels = [load(root, f["path"])["label"] for f in m["files"] if f["kind"] == "email"]
    c = Counter(lab["category"] for lab in labels)
    assert c == {"objection_within_15d": 5, "objection_after_15d": 4, "payment_delay": 4,
                 "document_request": 3, "noise": 4}
    assert all(lab["within_15_days"] == (lab["days_after_delivery"] <= 15)
               for lab in labels if lab["is_objection"])
    assert len(m["injection_samples"]) >= 3 and sum(lab["injection"] for lab in labels) == 3


def test_gst_fixtures(world):
    root, m = world
    ims = [r for resp in load(root, "gst/ims_supplier_view.json") for b in resp["b2b"] for r in b["inv"]]
    assert {r["action"] for r in ims} == {"A", "P", "N"}
    assert all(r["gstr2b_gendt"] for r in ims)
    rej = [r for resp in load(root, "gst/ims_supplier_view_reversal.json") for b in resp["b2b"] for r in b["inv"]]
    assert rej and {r["action"] for r in rej} == {"R"}
    g1 = load(root, "gst/gstr1.json")
    assert sum(len(r["b2cl"]) for r in g1) == len(m["scenarios"]["gst_block"])
    assert load(root, "gst/ewb.json")


def test_bank_part_payments(world):
    root, m = world
    cr = [c for s in ("S1", "S2", "S3") for c in load(root, f"bank/{s}_statement.truth.json")["credits"]]
    per = Counter(c["invoice_id"] for c in cr)
    assert any(per[i] == 2 for i in m["scenarios"]["part_payment"])
    assert all(c["utr"] and c["date"] and c["amount"] > 0 for c in cr)
