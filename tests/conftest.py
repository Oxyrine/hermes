"""Database fixture: DATABASE_URL if set (CI postgres service), else an embedded Postgres 16."""

import os
import tempfile

import psycopg
import pytest


@pytest.fixture(scope="session")
def _server_url():
    if url := os.environ.get("DATABASE_URL"):
        yield url
        return
    import pixeltable_pgserver as pgserver

    with tempfile.TemporaryDirectory() as d:
        srv = pgserver.get_server(d)
        yield srv.get_uri()
        srv.cleanup()


@pytest.fixture
def dsn(_server_url):
    """A freshly migrated and seeded database for each test."""
    from hermes.ledger import db, seed

    with psycopg.connect(_server_url, autocommit=True) as conn:
        db.reset(conn)
        seed.run(conn)
    return _server_url
