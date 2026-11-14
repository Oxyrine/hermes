"""Postgres access: plain psycopg, no ORM. The schema is applied from schema.sql."""

import os
from contextlib import contextmanager
from pathlib import Path

import psycopg

SCHEMA = Path(__file__).with_name("schema.sql")


def database_url() -> str:
    return os.environ.get("DATABASE_URL", "postgresql://hermes:hermes-local-only@localhost:5432/hermes")


def reset(conn: psycopg.Connection) -> None:
    """Drop everything and recreate the schema. Development and tests only."""
    conn.execute("DROP SCHEMA public CASCADE")
    conn.execute("CREATE SCHEMA public")
    conn.execute(SCHEMA.read_text(encoding="utf-8"))


def as_tenant(conn: psycopg.Connection, tenant: str | None) -> None:
    """Drop to the policy-bound application role scoped to one tenant (None sees nothing)."""
    conn.execute("SET ROLE hermes_app")
    conn.execute("SELECT set_config('hermes.tenant', %s, false)", (tenant or "",))


@contextmanager
def scoped(conn: psycopg.Connection, tenant: str | None):
    """as_tenant for a block; the role and setting are cleared on the way out, so a shared
    connection never carries one request's tenant into the next."""
    as_tenant(conn, tenant)
    try:
        yield conn
    finally:
        conn.execute("RESET ROLE")
        conn.execute("RESET hermes.tenant")
