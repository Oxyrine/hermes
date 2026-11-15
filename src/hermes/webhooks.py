"""Webhooks to lenders: subscribe, fan an event out to the tenant's subscriptions, and deliver
signed payloads with exponential backoff for 24 hours. Payloads carry ids only. A subscription's
signing secret is derived from a server key and its id (HMAC), so nothing secret is stored; it is
shown once, at subscription."""

import hashlib
import hmac
import ipaddress
import json
import os
import socket
from datetime import timedelta
from urllib.parse import urlsplit

from psycopg.rows import dict_row

EVENTS = ("invoice.state_changed", "invoice.hard_flag", "collateral.ltv_breach",
          "action.awaiting_lender")
GIVE_UP = timedelta(hours=24)
FIRST_DELAY, MAX_DELAY = timedelta(seconds=30), timedelta(hours=4)
HEADER = "X-Hermes-Signature"


def signing_key() -> str:
    key = os.environ.get("HERMES_WEBHOOK_KEY") or (
        "dev-only-webhook-key-do-not-use-0123456789"
        if os.environ.get("HERMES_ENV") == "development" else "")
    if not key:
        raise RuntimeError("HERMES_WEBHOOK_KEY must be set outside development")
    return key


def secret_for(key: str, subscription_id) -> str:
    return hmac.new(key.encode(), str(subscription_id).encode(), hashlib.sha256).hexdigest()


def sign(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def check_url(url: str, dev: bool) -> None:
    """Outside development: https only, and no host that resolves to a private, loopback or
    otherwise non-public address. ponytail: resolved again at delivery, but a DNS answer that
    changes between that check and the connection is not pinned; pin the address if it matters."""
    u = urlsplit(url)
    if u.scheme not in ("http", "https") or not u.hostname:
        raise ValueError("webhook url must be an absolute http(s) url")
    if dev:
        return
    if u.scheme != "https":
        raise ValueError("webhook url must be https")
    try:
        found = {a[4][0] for a in socket.getaddrinfo(u.hostname, u.port or 443)}
    except socket.gaierror:
        raise ValueError("webhook host does not resolve") from None
    for a in found:
        ip = ipaddress.ip_address(a.split("%")[0])
        if not (getattr(ip, "ipv4_mapped", None) or ip).is_global:
            raise ValueError("private or loopback addresses are refused")


def subscribe(conn, tenant_id, url, events, dev: bool, key: str) -> dict:
    events = list(events or EVENTS)
    if not isinstance(url, str) or any(e not in EVENTS for e in events):
        raise ValueError(f"url and events (any of {', '.join(EVENTS)}) are required")
    check_url(url, dev)
    sid = conn.execute("INSERT INTO webhook_subscription (tenant_id, url, events) "
                       "VALUES (%s,%s,%s) RETURNING id", (tenant_id, url, events)).fetchone()[0]
    return {"id": str(sid), "url": url, "events": events, "secret": secret_for(key, sid)}


def list_subscriptions(conn, tenant_id) -> list[dict]:
    return conn.cursor(row_factory=dict_row).execute(
        "SELECT id::text, url, events, active FROM webhook_subscription WHERE tenant_id=%s "
        "ORDER BY id", (tenant_id,)).fetchall()


def publish(conn, tenant_id, event: str, ids: dict) -> None:
    """Queue a delivery of event to each active subscription of this tenant that wants it."""
    conn.execute(
        "INSERT INTO webhook_delivery (tenant_id, subscription_id, event, payload, next_attempt_at) "
        "SELECT tenant_id, id, %s, %s::jsonb, now() FROM webhook_subscription "
        "WHERE tenant_id=%s AND active AND %s = ANY(events)",
        (event, json.dumps(ids), tenant_id, event))


def _post(url: str, body: bytes, headers: dict) -> int:
    import httpx  # does not follow redirects by default

    return httpx.post(url, content=body, headers=headers, timeout=10).status_code


def deliver_due(conn, key: str, dev: bool = False, post=_post) -> int:
    """Attempt every delivery that is due; returns how many succeeded. Each attempt is recorded
    in webhook_attempt. A failure is retried after 30s, 1m, 2m... (at most 4h) until 24 hours after
    the event, then dropped. ponytail: one worker; add a claim (SKIP LOCKED) before running two."""
    due = conn.cursor(row_factory=dict_row).execute(
        "SELECT d.id, d.tenant_id, d.subscription_id, d.event, d.payload, d.attempts, d.created_at, "
        "s.url FROM webhook_delivery d JOIN webhook_subscription s ON s.id=d.subscription_id "
        "WHERE d.delivered_at IS NULL AND d.next_attempt_at <= now() ORDER BY d.next_attempt_at, d.id"
    ).fetchall()
    sent = 0
    for d in due:
        body = json.dumps({"id": str(d["id"]), "event": d["event"],
                           "created_at": d["created_at"].isoformat(), **d["payload"]},
                          sort_keys=True, separators=(",", ":")).encode()
        headers = {"Content-Type": "application/json", "X-Hermes-Event": d["event"],
                   HEADER: sign(secret_for(key, d["subscription_id"]), body)}
        status = error = None
        try:
            check_url(d["url"], dev)
            status = post(d["url"], body, headers)
        except Exception as e:  # noqa: BLE001 any failure to deliver is an attempt to record
            error = f"{type(e).__name__}: {e}"[:300]
        ok = status is not None and 200 <= status < 300
        conn.execute("INSERT INTO webhook_attempt (tenant_id, delivery_id, status, error) "
                     "VALUES (%s,%s,%s,%s)", (d["tenant_id"], d["id"], status, error))
        delay = min(FIRST_DELAY * 2 ** d["attempts"], MAX_DELAY)
        conn.execute(
            "UPDATE webhook_delivery SET attempts=attempts+1, last_status=%s, "
            "delivered_at=CASE WHEN %s THEN now() END, next_attempt_at=CASE WHEN %s OR "
            "now()+%s > created_at+%s THEN NULL ELSE now()+%s END WHERE id=%s",
            (status, ok, ok, delay, GIVE_UP, delay, d["id"]))
        if ok:
            sent += 1
            if d["event"] == "invoice.hard_flag":
                conn.execute("UPDATE hard_flag_event SET delivered_at=COALESCE(delivered_at, now()) "
                             "WHERE id=%s AND tenant_id=%s",
                             (d["payload"]["flag_id"], d["tenant_id"]))
    return sent
