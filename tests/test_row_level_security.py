"""Ticket 29: the database enforces tenancy, even for a query that forgets its tenant filter."""

import psycopg
import pytest
from fastapi.testclient import TestClient

from hermes.api import create_app
from hermes.ledger import db as ledger_db
from test_seeded_invoice_api import SECRET, login, seeded_invoice_id


@pytest.fixture
def owner(dsn):
    with psycopg.connect(dsn, autocommit=True) as c:
        yield c


@pytest.fixture
def client(dsn):
    return TestClient(create_app(dsn, secret=SECRET, env="development"))


@pytest.fixture
def tenant_a(owner):
    return owner.execute("SELECT tenant_id::text FROM invoice").fetchone()[0]


@pytest.fixture
def tenant_b(owner):
    t = owner.execute("INSERT INTO tenant (name, kind, max_ltv, lender_rate_nominal) "
                      "SELECT 'Lender B', kind, max_ltv, lender_rate_nominal FROM tenant "
                      "RETURNING id::text").fetchone()[0]
    owner.execute("INSERT INTO app_user (tenant_id, email, role) VALUES (%s,'ops@lender-b.example',"
                  "'lender_ops')", (t,))
    return t


def test_unfiltered_query_as_app_role_sees_only_the_current_tenants_rows(owner, tenant_a, tenant_b):
    ledger_db.as_tenant(owner, tenant_b)
    assert owner.execute("SELECT count(*) FROM invoice").fetchone()[0] == 0
    assert owner.execute("SELECT count(*) FROM app_user").fetchone()[0] == 1
    ledger_db.as_tenant(owner, tenant_a)
    assert owner.execute("SELECT count(*) FROM invoice").fetchone()[0] == 1
    assert owner.execute("SELECT count(*) FROM buyer").fetchone()[0] >= 1  # global
    assert owner.execute("SELECT count(*) FROM bank_rate").fetchone()[0] >= 1  # global


def test_app_role_cannot_bypass_policies_or_cross_tenant_write(owner, tenant_a, tenant_b):
    ledger_db.as_tenant(owner, tenant_b)
    assert owner.execute("SELECT rolbypassrls, rolsuper FROM pg_roles WHERE rolname=current_user"
                         ).fetchone() == (False, False)
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        owner.execute("INSERT INTO app_user (tenant_id, email, role) VALUES (%s,'x@y.z','lender_ops')",
                      (tenant_a,))


def test_every_tenant_scoped_table_has_row_level_security(owner):
    bad = owner.execute(
        "SELECT c.relname FROM pg_class c JOIN pg_attribute a ON a.attrelid=c.oid AND a.attname='tenant_id' "
        "WHERE c.relkind='r' AND c.relnamespace='public'::regnamespace AND NOT c.relrowsecurity").fetchall()
    assert bad == []


def test_unset_tenant_setting_sees_nothing(owner):
    ledger_db.as_tenant(owner, None)
    assert owner.execute("SELECT count(*) FROM invoice").fetchone()[0] == 0


def test_second_tenant_user_reads_nothing_of_the_first_including_by_id(client, tenant_a, tenant_b):
    inv = seeded_invoice_id(client, login(client))
    h = login(client, "ops@lender-b.example")
    assert client.get("/v1/invoices", headers=h).json() == []
    assert client.get(f"/v1/invoices/{inv}", headers=h).status_code == 404
    assert client.get(f"/v1/invoices/{inv}/timeline", headers=h).status_code == 404


def test_tenant_setting_does_not_leak_between_requests_on_a_shared_connection(dsn, tenant_a):
    from hermes.ledger.db import scoped
    with psycopg.connect(dsn, autocommit=True) as c:
        with scoped(c, tenant_a):
            assert c.execute("SELECT count(*) FROM invoice").fetchone()[0] == 1
        assert c.execute("SELECT current_user = session_user").fetchone()[0]
        assert c.execute("SELECT current_setting('hermes.tenant', true)").fetchone()[0] in (None, "")
