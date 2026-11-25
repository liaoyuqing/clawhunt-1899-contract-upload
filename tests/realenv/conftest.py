"""Fixtures for the REAL-environment verification suite.

The default suite under ``tests/`` runs on SQLite + moto so it can run on any
machine.  The tests in THIS directory must talk to a **real MinIO server** and
a **real PostgreSQL 16 server**, because order 1899 asks for MinIO by name in
AC1 and names PostgreSQL 16 in the unified technical constraints.

They are opt-in: when the environment variables below are absent every test
here is skipped, so ``python -m pytest`` keeps its original SQLite + moto
result ("no docker / no MinIO / no PostgreSQL" machines stay green).

  CONTRACT_TEST_S3_ENDPOINT       e.g. http://127.0.0.1:9000
  CONTRACT_TEST_S3_SECRET_KEY     e.g. minioadmin
  CONTRACT_TEST_S3_ACCESS_KEY_ID  e.g. minioadmin (default)
  CONTRACT_TEST_DATABASE_URL      postgresql+psycopg://postgres@127.0.0.1:55432/contracts_realenv
  CONTRACT_TEST_BUCKET            bucket used by the AC1 evidence run (default contract-realenv)
"""

from __future__ import annotations

import os
import uuid

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.storage.s3_adapter import S3StorageAdapter

S3_ENDPOINT = os.environ.get("CONTRACT_TEST_S3_ENDPOINT")
S3_SECRET_KEY = os.environ.get("CONTRACT_TEST_S3_SECRET_KEY")
S3_ACCESS_KEY_ID = os.environ.get("CONTRACT_TEST_S3_ACCESS_KEY_ID") or "minioadmin"
DATABASE_URL = os.environ.get("CONTRACT_TEST_DATABASE_URL")
EVIDENCE_BUCKET = os.environ.get("CONTRACT_TEST_BUCKET") or "contract-realenv"

ORG_ID = "org-realenv-0001"
OTHER_ORG_ID = "org-realenv-0002"


def missing_environment() -> list[str]:
    """Return the names of the environment variables that are still missing."""
    required = {
        "CONTRACT_TEST_S3_ENDPOINT": S3_ENDPOINT,
        "CONTRACT_TEST_S3_SECRET_KEY": S3_SECRET_KEY,
        "CONTRACT_TEST_DATABASE_URL": DATABASE_URL,
    }
    return [name for name, value in required.items() if not value]


MISSING = missing_environment()

requires_real_env = pytest.mark.skipif(
    bool(MISSING),
    reason=("real MinIO / PostgreSQL 16 suite needs " + ", ".join(MISSING)),
)


@pytest.fixture()
def evidence_bucket() -> str:
    """Deterministic bucket so ``mc ls --recursive`` can be run afterwards."""
    return EVIDENCE_BUCKET


@pytest.fixture()
def fresh_bucket() -> str:
    """A throw-away bucket per test so object counts are exact."""
    return f"contract-realenv-{uuid.uuid4().hex[:10]}"


def build_settings(bucket: str, **overrides) -> Settings:
    values = dict(
        endpoint=S3_ENDPOINT,
        bucket=bucket,
        secret_key=S3_SECRET_KEY,
        access_key_id=S3_ACCESS_KEY_ID,
        region="us-east-1",
        database_url=DATABASE_URL,
        site_timezone="Asia/Shanghai",
        max_file_size=20 * 1024 * 1024,
        presign_ttl_seconds=300,
    )
    values.update(overrides)
    return Settings(**values)


@pytest.fixture()
def make_settings():
    """Return a factory so a test can pick its own bucket."""

    def _make(bucket: str, **overrides) -> Settings:
        return build_settings(bucket, **overrides)

    return _make


@pytest.fixture()
def open_client(make_settings):
    """Yield a factory that starts the app against the REAL MinIO + PostgreSQL.

    ``with TestClient(app)`` runs the lifespan, which resolves the settings,
    creates the engine, calls ``create_all`` (idempotent - the tables already
    exist because ``alembic upgrade head`` created them in the evidence run)
    and configures the S3 adapter on the real endpoint.
    """
    clients = []

    def _open(bucket: str, **overrides):
        settings = make_settings(bucket, **overrides)
        app = create_app(settings)
        client = TestClient(app)
        client.__enter__()
        adapter = S3StorageAdapter(
            endpoint=settings.endpoint,
            bucket=settings.bucket,
            secret_key=settings.secret_key,
            access_key_id=settings.access_key_id,
            region=settings.region,
        )
        adapter.ensure_bucket()
        app.state.adapter = adapter
        clients.append((client, app))
        return client, app, adapter

    yield _open

    for client, _app in clients:
        client.__exit__(None, None, None)


@pytest.fixture()
def real_client(open_client, evidence_bucket):
    client, app, adapter = open_client(evidence_bucket)
    return client, adapter


@pytest.fixture()
def isolated_client(open_client, fresh_bucket):
    """App on a throw-away bucket, so tests cannot pollute the AC1 evidence bucket."""
    client, app, adapter = open_client(fresh_bucket)
    return client, adapter


@pytest.fixture()
def headers():
    """A fresh organisation per test, so row counts are exact on a shared DB."""
    return {
        "X-Org-Id": f"{ORG_ID}-{uuid.uuid4().hex[:10]}",
        "X-User-Id": "user-realenv",
        "X-Roles": "admin,contract_manager",
    }


@pytest.fixture()
def other_org_headers():
    return {
        "X-Org-Id": f"{OTHER_ORG_ID}-{uuid.uuid4().hex[:10]}",
        "X-User-Id": "user-realenv-other",
        "X-Roles": "admin,contract_manager",
    }