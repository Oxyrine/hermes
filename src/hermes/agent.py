"""Scripted agent runner: implements the product spec's event table (section 7). It reads and
writes only through the HTTP API, with the agent role's token. `http` is anything with
`.request(method, url, json=, headers=)` returning a response with `.status_code` and `.json()`."""


class ScriptedAgent:
    def __init__(self, http, token: str):
        self.http, self.headers, self.tool_calls = http, {"Authorization": f"Bearer {token}"}, 0

    def call(self, method: str, path: str, **kw) -> dict:
        self.tool_calls += 1
        r = self.http.request(method, path, headers=self.headers, **kw)
        if r.status_code != 200:
            raise RuntimeError(f"{method} {path}: {r.status_code} {r.text}")
        return r.json()

    def handle(self, event: dict) -> None:
        # ponytail: one handler so far; each later ticket adds its row of the event table
        {"deadline.passed": self.deadline_passed,
         "payment.received": self.payment_received,
         "offer.expired": self.offer_expired,
         "bank_rate.changed": self.bank_rate_changed,
         "ims.action_changed": self.ims_action_changed,
         "invoice.hard_flag": self.hard_flag,
         "source.record.ingested": self.record_ingested,
         "action.approved": lambda e: None,
         "document.ingested": lambda e: None}[event["kind"]](event)  # published for later tickets (extraction) to act on

    def deadline_passed(self, event: dict) -> None:
        """Re-run interest and collateral (the invoice read runs and stores both engines as of
        the event date), then move the invoice to overdue if it is not already."""
        as_of, inv = event["payload"]["as_of"], event["invoice_id"]
        view = self.call("GET", f"/v1/invoices/{inv}", params={"as_of": as_of})
        if view["state"] in ("verified", "financeable", "advanced"):
            self.call("POST", f"/v1/invoices/{inv}/state", json={"to": "overdue", "as_of": as_of})
            view["state"] = "overdue"
        if view["state"] == "overdue":
            self.call("POST", f"/v1/invoices/{inv}/actions",
                      json={"kind": "settlement_offer", "as_of": as_of})

    def payment_received(self, event: dict) -> None:
        """Re-run interest and collateral as of the payment date (the read does both); when the
        receipts cover the amount due, move to paid and run the waterfall. The lender then
        confirms repayment, which closes the invoice."""
        as_of, inv = event["payload"]["as_of"], event["invoice_id"]
        view = self.call("GET", f"/v1/invoices/{inv}", params={"as_of": as_of})
        if view["state"] in ("paid", "closed"):
            return
        try:
            self.call("POST", f"/v1/invoices/{inv}/state", json={"to": "paid", "as_of": as_of})
        except RuntimeError as e:
            if " 409 " not in str(e):  # guard refused: receipts do not cover the amount due yet
                raise
            return
        self.call("POST", f"/v1/invoices/{inv}/waterfall", json={"as_of": as_of})

    def offer_expired(self, event: dict) -> None:
        """The offer lapsed or was refused: draft the dispute pack for the supplier to release.
        The agent never files; it cannot reach the portal."""
        self.call("POST", f"/v1/invoices/{event['invoice_id']}/actions",
                  json={"kind": "odr_pack", "as_of": event["payload"]["as_of"]})

    def bank_rate_changed(self, event: dict) -> None:
        """Re-run interest and collateral as of the event date (the read does both); no state moves."""
        self.call("GET", f"/v1/invoices/{event['invoice_id']}", params={"as_of": event["payload"]["as_of"]})

    def hard_flag(self, event: dict) -> None:
        """A hard flag on a funded invoice: re-read it (re-runs evidence and the collateral alert)
        and stop for a person by proposing a review, whatever the score."""
        inv, as_of = event["invoice_id"], event["payload"]["as_of"]
        view = self.call("GET", f"/v1/invoices/{inv}", params={"as_of": as_of})
        self.call("POST", f"/v1/invoices/{inv}/actions", json={"kind": "review", "draft": {
            "flags": [f["kind"] for f in view["hard_flags"]],
            "alerts": (view["collateral"] or {}).get("alerts", []),
            "score": view["evidence"]["score"], "band": view["evidence"]["band"], "as_of": as_of}})

    def record_ingested(self, event: dict) -> None:
        if event["payload"]["source"] == "gstr1":
            self.gst_check(event)

    def ims_action_changed(self, event: dict) -> None:
        self.bank_rate_changed(event)  # the read re-runs evidence score and collateral
        self.gst_check(event)

    def gst_check(self, event: dict) -> None:
        """Block a verified invoice the buyer cannot see (or whose IMS rejection the supplier can
        fix) and draft the correction for the supplier; return a blocked one to verified once IMS
        accepts it, then try financeable (the server's guard decides). Guards refuse with 409."""
        as_of, inv = event["payload"]["as_of"], event["invoice_id"]
        state = self.call("GET", f"/v1/invoices/{inv}", params={"as_of": as_of})["state"]
        steps = {"verified": ("gst_blocked",), "gst_blocked": ("verified", "financeable")}.get(state, ())
        for to in steps:
            try:
                self.call("POST", f"/v1/invoices/{inv}/state", json={"to": to, "as_of": as_of})
            except RuntimeError as e:
                if " 409 " not in str(e):
                    raise
                return
        if steps[:1] == ("gst_blocked",):
            self.call("POST", f"/v1/invoices/{inv}/actions", json={"kind": "gstr1a_draft", "as_of": as_of})
