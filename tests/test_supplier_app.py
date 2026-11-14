"""Ticket 31: the supplier's own invoice view, through the API."""

import psycopg
import pytest
from fastapi.testclient import TestClient

from hermes.api import create_app
from test_onboarding_and_upload import onboard, supplier_login
from test_seeded_invoice_api import SECRET, login


@pytest.fixture
def client(dsn):
    return TestClient(create_app(dsn, secret=SECRET, env="development"))


@pytest.fixture
def db(dsn):
    with psycopg.connect(dsn, autocommit=True) as c:
        yield c


def mine(client, h, as_of="2026-11-14"):
    return client.get("/v1/me/invoices", params={"as_of": as_of}, headers=h)


def test_status_is_plain_language_and_cash_offer_shows_its_cost(client):
    (inv,) = mine(client, supplier_login(client)).json()
    assert inv["status"].startswith("Overdue 60 days; interest so far \u20b9")
    assert inv["cash"]["advance"] and "a year" in inv["cash"]["cost"]
    assert "accountant or a lawyer" in inv["advice"] and "Deadline rule" in inv["rule"]
    assert mine(client, supplier_login(client), "2026-09-01").json()[0]["status"].endswith("Payment due 15 Sep")


def test_interest_and_cash_are_hidden_when_ineligible(client, db):
    db.execute("UPDATE udyam_classification SET class='medium'")
    (inv,) = mine(client, supplier_login(client)).json()
    assert inv["status"] == "Overdue 60 days" and inv["cash"] is None


def test_a_supplier_sees_only_their_own_invoices_and_others_are_refused(client, db):
    other = onboard(client).json()["id"]
    db.execute("INSERT INTO app_user (tenant_id, email, role, supplier_id) "
               "SELECT tenant_id, 'other@supplier.example', 'supplier', %s FROM app_user LIMIT 1", (other,))
    assert mine(client, login(client, "other@supplier.example")).json() == []
    assert len(mine(client, supplier_login(client)).json()) == 1
    assert mine(client, login(client)).status_code == 403  # lender staff use /v1/invoices
