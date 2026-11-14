"""Postgres access: plain psycopg, no ORM. The schema is applied from schema.sql."""

import os
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
