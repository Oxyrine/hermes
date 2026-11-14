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
        {"deadline.passed": self.deadline_passed}[event["kind"]](event)

    def deadline_passed(self, event: dict) -> None:
        """Re-run interest and collateral (the invoice read runs and stores both engines as of
        the event date), then move the invoice to overdue if it is not already."""
        as_of, inv = event["payload"]["as_of"], event["invoice_id"]
        view = self.call("GET", f"/v1/invoices/{inv}", params={"as_of": as_of})
        if view["state"] in ("verified", "financeable", "advanced"):
            self.call("POST", f"/v1/invoices/{inv}/state", json={"to": "overdue", "as_of": as_of})
