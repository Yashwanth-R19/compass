"""Shared fixtures: an isolated, ephemeral test database.

Every DB-touching test gets a pristine schema with zero manual cleanup:

- ``test_database_url`` (session-scoped) starts an ephemeral Postgres via
  testcontainers, or falls back to ``TEST_DATABASE_URL`` if Docker isn't
  available, or skips the DB tests with a clear message. It never falls back
  to the production ``DATABASE_URL``.
- ``db_session`` (function-scoped) opens one connection, begins an outer
  transaction, binds a ``Session`` to it, yields, then rolls the outer
  transaction back -- every test starts from an empty, migrated schema.
- ``client`` builds a FastAPI ``TestClient`` with the app's ``get_db``
  dependency overridden to hand out ``db_session``.

To write a new DB test: take ``db_session`` (or ``client``) as a fixture
argument, insert rows / call engines directly, and assert. No explicit
cleanup helper, no ``finally`` block -- the rollback above erases it.
"""

import os
import subprocess
import sys
from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.engine import Connection, Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

import app.db.base as db_base
import app.jobs.runner as job_runner
from app.db.base import get_db
from app.main import app

BACKEND_ROOT = Path(__file__).resolve().parents[1]


def _run_migrations(database_url: str) -> None:
    env = os.environ.copy()
    env["DATABASE_URL"] = database_url
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=BACKEND_ROOT,
        env=env,
        check=True,
    )


@pytest.fixture(scope="session")
def test_database_url() -> Generator[str, None, None]:
    # An explicit TEST_DATABASE_URL always wins -- this is what CI sets to
    # point at its postgres service container, so a job that already has a
    # database doesn't also pay to spin up a redundant nested one via
    # testcontainers (see .github/workflows/ci.yml).
    env_url = os.environ.get("TEST_DATABASE_URL")
    if env_url:
        _run_migrations(env_url)
        yield env_url
        return

    try:
        from testcontainers.postgres import PostgresContainer

        container = PostgresContainer("postgres:16-alpine", driver="psycopg")
        container.start()
    except Exception as exc:
        pytest.skip(
            f"No Docker available for testcontainers ({exc!r}) and "
            "TEST_DATABASE_URL is not set. Start Docker Desktop, or set "
            "TEST_DATABASE_URL to a running Postgres 16 instance, to run "
            "the database-backed tests."
        )
        return

    try:
        url = container.get_connection_url()
        _run_migrations(url)
        yield url
    finally:
        container.stop()


@pytest.fixture(scope="session")
def _engine(test_database_url: str) -> Generator[Engine, None, None]:
    engine = create_engine(test_database_url, future=True)
    yield engine
    engine.dispose()


@pytest.fixture
def db_session(_engine: Engine, monkeypatch: pytest.MonkeyPatch) -> Generator[Session, None, None]:
    connection: Connection = _engine.connect()
    outer_transaction = connection.begin()
    connection.begin_nested()

    session_factory = sessionmaker(bind=connection, autoflush=False, autocommit=False, future=True)

    @event.listens_for(session_factory, "after_transaction_end")
    def _restart_savepoint(session: Session, transaction: object) -> None:
        # Lets inner code commit freely (RiskEngine etc. call session.commit()
        # mid-run, and run_ingestion_job commits repeatedly for progress
        # tracking) without ever touching the outer transaction we roll back
        # below -- each "commit" just releases and reopens a SAVEPOINT. This
        # is the standard SQLAlchemy "join a Session into an external
        # transaction" recipe.
        if connection.closed:
            return
        if not connection.in_nested_transaction():
            connection.begin_nested()

    # run_ingestion_job is deliberately transport-agnostic (CLAUDE.md) and
    # opens its own `SessionLocal()` rather than accepting a session. `from
    # app.db.base import SessionLocal` in app/jobs/runner.py bound that name
    # into the runner module's own namespace at import time, so patching
    # app.db.base.SessionLocal alone would not be seen by the runner -- both
    # bindings must point at the same connection-bound factory for a job-
    # runner test to land its writes in this test's rolled-back transaction.
    monkeypatch.setattr(db_base, "SessionLocal", session_factory)
    monkeypatch.setattr(job_runner, "SessionLocal", session_factory)

    session = session_factory()
    try:
        yield session
    finally:
        session.close()
        outer_transaction.rollback()
        connection.close()


@pytest.fixture
def client(db_session: Session) -> Generator[TestClient, None, None]:
    def _get_test_db() -> Generator[Session, None, None]:
        yield db_session

    app.dependency_overrides[get_db] = _get_test_db
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.pop(get_db, None)
