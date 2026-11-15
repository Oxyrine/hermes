"""Store what the model read as a fact (ticket 20) and apply it once people confirm. The model is
not trusted: the quote must be in the stored document, the date and term must be well formed, and
a reading that fails goes to a person as a review. A good one becomes a confirmation action; no
deadline, interest or collateral changes, and nothing re-runs, until the action is approved
(service.decide_action calls `apply` then)."""

import json
from datetime import date, timedelta

from psycopg.rows import dict_row

from hermes.checks import check_quotes
from hermes.engines.deadline.engine import WINDOW_DAYS
from hermes.facts import doc_text
from hermes.ledger import ingest, service, states


def _doc(conn, tenant_id, document_id, types):
    row = conn.cursor(row_factory=dict_row).execute(
        "SELECT d.id::text, d.invoice_id::text, d.doc_type, d.content, i.invoice_no FROM document d "
        "JOIN invoice i ON i.id=d.invoice_id WHERE d.id::text=%s AND d.tenant_id=%s "
        "AND d.content IS NOT NULL AND d.doc_type = ANY(%s)",
        (str(document_id), tenant_id, types)).fetchone()
    if row is None:
        raise service.NotFound("document")
    return row


def _quote_problems(doc, quote) -> list[str]:
    _, voided = check_quotes({"sources": {"quote": {"page": 1, "quote": quote}}},
                             doc_text(bytes(doc["content"]), doc["doc_type"]))
    return ["the quote is not in the document"] if voided else []


def _review(conn, tenant_id, doc, what, problems, reading, actor) -> dict:
    a = service.propose_action(conn, tenant_id, doc["invoice_id"], "review", {
        "reason": f"{what} could not be used", "problems": problems, "document_id": doc["id"],
        "reading": reading}, actor)
    return {"status": "review", "action_id": a["id"], "problems": problems}


def store_objection(conn, tenant_id, document_id: str, payload: dict, actor: str) -> dict:
    """-> {"status": "not_objection" | "proposed" | "review", "action_id"}."""
    doc = _doc(conn, tenant_id, document_id, ["email", "debit_note"])
    r = payload.get("result")
    if not isinstance(r, dict):
        return _review(conn, tenant_id, doc, "the objection reading",
                       [payload.get("reason") or "the model gave no usable answer"], None, actor)
    if r.get("is_objection") is not True:
        return {"status": "not_objection"}
    problems = _quote_problems(doc, r.get("quote") or "")
    try:
        date.fromisoformat(r.get("raised_on") or "")
    except ValueError:
        problems.append("raised_on is not a date")
    if doc["invoice_no"] not in (r.get("invoice_refs") or []):
        problems.append("the objection does not name this invoice")
    if problems:
        return _review(conn, tenant_id, doc, "the objection reading", problems, r, actor)
    if conn.execute("SELECT 1 FROM action_request WHERE invoice_id=%s AND kind='objection' AND "
                    "draft->>'document_id'=%s", (doc["invoice_id"], doc["id"])).fetchone():
        return {"status": "proposed", "action_id": None}  # already waiting or decided
    a = service.propose_action(conn, tenant_id, doc["invoice_id"], "objection", {
        "quote": r["quote"], "raised_on": r["raised_on"], "removed_on": None,
        "invoice_refs": r["invoice_refs"], "confidence": r["confidence"], "model": payload.get("model"),
        "document_id": doc["id"]}, actor)
    return {"status": "proposed", "action_id": a["id"]}


def store_contract_terms(conn, tenant_id, document_id: str, payload: dict, actor: str) -> dict:
    doc = _doc(conn, tenant_id, document_id, ["contract"])
    r = payload.get("result")
    if not isinstance(r, dict):
        return _review(conn, tenant_id, doc, "the contract reading",
                       [payload.get("reason") or "the model gave no usable answer"], None, actor)
    days = r.get("payment_days")
    if days is None:
        return {"status": "no_term"}
    problems = _quote_problems(doc, r.get("clause_quote") or "")
    if isinstance(days, bool) or not isinstance(days, int) or days < 0:
        problems.append("payment_days is not a whole number of days")
    if problems:
        return _review(conn, tenant_id, doc, "the contract reading", problems, r, actor)
    a = service.propose_action(conn, tenant_id, doc["invoice_id"], "contract_terms", {
        "payment_days": str(days), "from_event": r.get("from_event"), "clause_quote": r["clause_quote"],
        "page": r.get("page"), "confidence": r["confidence"], "model": payload.get("model"),
        "document_id": doc["id"]}, actor)
    return {"status": "proposed", "action_id": a["id"]}


def apply(conn, row: dict, final: dict, user_id: str) -> None:
    """A confirmed fact takes effect (called with the approved action's row and its draft as
    corrected by the approver). Raises ValueError/Refused to roll the approval back."""
    t, inv = row["tenant_id"], row["invoice_id"]
    if row["kind"] == "contract_terms":
        cid = conn.execute("SELECT contract_id FROM invoice WHERE id=%s", (inv,)).fetchone()[0]
        if cid is None:
            raise states.Refused("the invoice has no contract to store the term on yet")
        conn.execute(
            "UPDATE contract SET written_payment_days=%s, terms_source=%s::jsonb, terms_confirmed_by=%s, "
            "terms_confirmed_at=now() WHERE id=%s",
            (int(final["payment_days"]), json.dumps({"doc_id": final["document_id"],
                                                     "page": final.get("page"),
                                                     "quote": final["clause_quote"]}), user_id, cid))
    elif final.get("raised_on"):  # objection; one with no date (free text) only raises the flag
        raised = date.fromisoformat(final["raised_on"])
        if final.get("removed_on") and date.fromisoformat(final["removed_on"]) < raised:
            raise ValueError("an objection cannot be removed before it was raised")
        delivery = conn.execute(
            "SELECT extracted->>'delivery_date' FROM document WHERE invoice_id=%s AND "
            "extracted->>'delivery_date' IS NOT NULL ORDER BY doc_type, id LIMIT 1", (inv,)).fetchone()
        if delivery and raised <= date.fromisoformat(delivery[0]) + timedelta(days=WINDOW_DAYS):
            ingest._evidence(conn, t, inv, "written_objection_15d",
                             {"action_id": str(row["id"]), "document_id": final.get("document_id")})
    ingest._set_due(conn, inv)  # the stored due date follows the new term or acceptance date
