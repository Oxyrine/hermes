"""Source adapters (product spec section 3): every source enters through `fetch(supplier_id, since)`
and returns `RawRecord`s. The prototype adapter reads the synthetic fixtures; a live adapter (GSP,
Account Aggregator, Gmail) is another class with the same `fetch`. An adapter refuses to fetch
unless the supplier has a live consent for its source and purpose."""

import base64
import hashlib
import hmac
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from reportlab.graphics.barcode.qrencoder import QRCode, QRRSBlock, QRUtil

from hermes.ledger import states
from hermes.synthetic.generate import QR_TEST_KEY

DOC_KINDS = ("invoice", "po", "grn", "challan", "contract")
NOT_RAW = ("sources", "injection", "qr_payload")  # ground-truth bookkeeping, not part of a document


@dataclass
class RawRecord:
    source: str
    external_id: str  # IRN, EWB no., message id, UTR, ...
    payload: dict  # stored as-is
    fetched_at: datetime
    consent_id: str  # which consent covered this pull


def decode_qr(pdf: bytes) -> str:
    """The text of the QR code drawn on the first page of an invoice PDF. The prototype's PDFs draw
    it as vector runs, so this rebuilds the module grid from them and reads it back with
    reportlab's own QR tables. ponytail: clean byte-mode codes from that generator only, no error
    correction; the pilot reads the signed QR from the IRP API instead."""
    s = pdf.decode("latin1")
    box = float(re.search(r"n 0 0 ([\d.]+) [\d.]+ re n", s)[1])
    runs = [tuple(map(float, m)) for m in re.findall(r"n ([\d.]+) ([\d.]+) ([\d.]+) ([\d.]+) re f\*", s)]
    mod = min(h for *_, h in runs)
    n = round(box / mod) - 8  # four quiet-zone modules each side
    grid = [[False] * n for _ in range(n)]
    for x, y, w, h in runs:
        for c in range(round(x / mod) - 4, round((x + w) / mod) - 4):
            grid[round((box - y - h) / mod) - 4][c] = True
    ver = (n - 17) // 4
    info = sum(grid[i + (i > 5)][8] << i for i in range(8)) | sum(grid[n - 15 + i][8] << i for i in range(8, 15))
    level, mask = next((lv, m) for lv in (1, 0, 3, 2) for m in range(8)
                       if QRUtil.getBCHTypeInfo((lv << 3) | m) == info)
    qr, unmask = QRCode(ver, level), QRUtil.getMask(mask)
    qr.moduleCount = n
    bits = [grid[r][c] ^ unmask(r, c) for c, r in qr.dataPosIterator()]
    words = [int("".join("1" if b else "0" for b in bits[i:i + 8]), 2) for i in range(0, len(bits) // 8 * 8, 8)]
    sizes = [b.dataCount for b in QRRSBlock.getRSBlocks(ver, level)]
    blocks, i = [[] for _ in sizes], 0
    for k in range(max(sizes)):  # data words are interleaved across the blocks
        for j, size in enumerate(sizes):
            if k < size:
                blocks[j].append(words[i])
                i += 1
    stream = "".join(f"{w:08b}" for blk in blocks for w in blk)
    assert stream[:4] == "0100", "not byte mode"
    width = 8 if ver < 10 else 16
    length = int(stream[4:4 + width], 2)
    body = stream[4 + width:4 + width + 8 * length]
    return bytes(int(body[i:i + 8], 2) for i in range(0, len(body), 8)).decode()


def qr_claims(qr: str) -> tuple[dict, bool]:
    """The claims in a signed e-invoice QR (a JWT) and whether its signature verifies."""
    head, body, sig = qr.split(".")
    pad = lambda t: t + "=" * (-len(t) % 4)
    good = hmac.new(QR_TEST_KEY, f"{head}.{body}".encode(), hashlib.sha256).digest()
    return json.loads(base64.urlsafe_b64decode(pad(body))), hmac.compare_digest(
        good, base64.urlsafe_b64decode(pad(sig)))


def _json(root: Path, rel: str):
    return json.loads((root / rel).read_text(encoding="utf-8"))


def _ims(root, m, s, fixture):
    for r in _json(root, f"gst/{fixture or 'ims_supplier_view'}.json"):
        if r["gstin"] == s["gstin"]:
            for b in r["b2b"]:
                for inv in b["inv"]:
                    yield inv["inum"], {"gstin": r["gstin"], "rtnprd": r["rtnprd"], "ctin": b["ctin"]} | inv


def _gstr1(root, m, s, fixture):
    for r in _json(root, f"gst/{fixture or 'gstr1'}.json"):
        if r["gstin"] == s["gstin"]:
            head = {"gstin": r["gstin"], "fp": r["fp"]}
            for inv in r["b2cl"]:  # filed as B2C large: no buyer GSTIN, hidden from the buyer
                yield inv["inum"], head | {"table": "b2cl", "ctin": None} | inv
            for b in r["b2b"]:
                for inv in b["inv"]:
                    yield inv["inum"], head | {"table": "b2b", "ctin": b["ctin"]} | inv


def _ewb(root, m, s, fixture):
    for e in _json(root, "gst/ewb.json"):
        if e["genGstin"] == s["gstin"]:
            yield str(e["ewbNo"]), e


def _bank(root, m, s, fixture):
    text = re.findall(rb"\((.*?)\) Tj", (root / f"bank/{s['id']}_statement.pdf").read_bytes())
    for line in (t.decode() for t in text):
        if c := re.fullmatch(r"(\d{4}-\d\d-\d\d) NEFT CR (\S+) (.+) (\d+\.\d\d)", line):
            yield c[2], {"date": c[1], "utr": c[2], "counterparty": c[3], "amount": c[4]}


def _einvoice(root, m, s, fixture):
    for i in _own(m, s):
        rel = f"docs/{i['id']}/invoice.pdf"
        qr = decode_qr((root / rel).read_bytes())
        yield qr_claims(qr)[0]["Irn"], {"filename": rel, "qr": qr}


def _documents(root, m, s, fixture):
    for i in _own(m, s):  # the supplier's folder for each invoice
        for kind in DOC_KINDS:
            rel = f"docs/{i['id']}/{kind}"
            if (root / f"{rel}.pdf").exists():
                truth = _json(root, f"{rel}.truth.json")
                yield f"{rel}.pdf", {
                    "invoice_no": i["invoice_no"], "filename": f"{rel}.pdf",
                    "content_type": "application/pdf",
                    "content_b64": base64.b64encode((root / f"{rel}.pdf").read_bytes()).decode(),
                    "fields": {k: v for k, v in truth.items() if k not in NOT_RAW}}


def _email(root, m, s, fixture):
    mine = {i["id"] for i in _own(m, s)}
    for p in sorted((root / "emails").glob("*.json")):  # only labelled threads, never the mailbox
        e = json.loads(p.read_text(encoding="utf-8"))
        if e["label"]["invoice_id"] in mine:
            yield e["thread_id"], {k: v for k, v in e.items() if k != "label"}


def _own(m, s):
    return [i for i in m["invoices"] if i["supplier"] == s["id"]]


READERS = {"ims_supplier_view": _ims, "gstr1": _gstr1, "ewb": _ewb, "bank_statement": _bank,
           "einvoice": _einvoice, "documents": _documents, "email": _email}


class FixtureAdapter:
    def __init__(self, source: str, conn, tenant_id, purpose: str, root, fixture: str | None = None):
        if fixture is not None and not re.fullmatch(r"[a-z0-9_]+", fixture):
            raise ValueError("fixture must be a plain name")
        self.source, self.conn, self.tenant_id, self.purpose = source, conn, tenant_id, purpose
        self.root, self.fixture = Path(root), fixture

    def fetch(self, supplier_id: str, since: datetime | None = None) -> list[RawRecord]:
        # ponytail: a fixture is a whole snapshot, so `since` is ignored; live adapters honour it
        row = self.conn.execute(
            "SELECT s.gstin, (SELECT c.id::text FROM consent c WHERE c.supplier_id=s.id AND "
            "c.tenant_id=s.tenant_id AND c.source=%s AND c.purpose=%s AND c.revoked_at IS NULL "
            "AND (c.expires_at IS NULL OR c.expires_at > now()) ORDER BY c.granted_at DESC LIMIT 1) "
            "FROM supplier s WHERE s.id=%s AND s.tenant_id=%s",
            (self.source, self.purpose, supplier_id, self.tenant_id)).fetchone()
        if row is None or row[1] is None:
            raise states.Refused(f"no live consent from the supplier for {self.source} "
                                 f"for {self.purpose}")
        m = _json(self.root, "manifest.json")
        sup = next((s for s in m["suppliers"] if s["gstin"] == row[0]), None)
        now = datetime.now(UTC)
        return [] if sup is None else [
            RawRecord(self.source, ext, payload, now, row[1])
            for ext, payload in READERS[self.source](self.root, m, sup, self.fixture)]
