"""Shared fixtures.

The object storage is a **real moto S3 server** (``ThreadedMotoServer``), so
boto3 talks to it over the real HTTP protocol stack (signing, multipart
uploads, presigned URLs) instead of an in-process mock.
"""

from __future__ import annotations

import os
import secrets

import pytest
from fastapi.testclient import TestClient
from moto.server import ThreadedMotoServer

from app.config import Settings
from app.db import create_db_engine, create_all
from app.doc.dispatch import RecognitionDispatcher
from app.main import create_app
from app.storage.s3_adapter import S3StorageAdapter

BUCKET = "contract-bucket"
ORG_ID = "org-0001"
OTHER_ORG_ID = "org-0002"


@pytest.fixture(scope="session")
def moto_server():
    server = ThreadedMotoServer(port=0)
    server.start()
    host, port = server.get_host_and_port()
    yield f"http://127.0.0.1:{port}"
    server.stop()


@pytest.fixture()
def database_url(tmp_path):
    """A WAL SQLite file so concurrent writers serialise instead of deadlocking.

    The shared-cache in-memory mode of SQLite raises SQLITE_LOCKED (table
    level) which the busy timeout cannot resolve; a WAL file gives the
    usual reader/writer concurrency of a real database.
    """
    path = tmp_path / f"contracts_{secrets.token_hex(6)}.db"
    return f"sqlite:///{path.as_posix()}"


@pytest.fixture()
def settings(moto_server, database_url):
    # every test gets its own bucket so object counts are deterministic
    return Settings(
        endpoint=moto_server,
        bucket=f"contract-bucket-{secrets.token_hex(6)}",
        secret_key="test-secret-key",
        access_key_id="test-access-key",
        region="us-east-1",
        database_url=database_url,
        site_timezone="Asia/Shanghai",
        max_file_size=20 * 1024 * 1024,
        presign_ttl_seconds=300,
    )


@pytest.fixture()
def adapter(settings):
    adapter = S3StorageAdapter(
        endpoint=settings.endpoint,
        bucket=settings.bucket,
        secret_key=settings.secret_key,
        access_key_id=settings.access_key_id,
        region=settings.region,
    )
    adapter.ensure_bucket()
    return adapter


@pytest.fixture()
def app(settings, adapter):
    application = create_app(settings)
    with TestClient(application) as client:
        application.state.adapter = adapter
        application.state.dispatcher = RecognitionDispatcher()
        yield application


@pytest.fixture()
def client(app):
    return TestClient(app)


@pytest.fixture()
def dispatcher(app):
    return app.state.dispatcher


@pytest.fixture()
def headers():
    return {
        "X-Org-Id": ORG_ID,
        "X-User-Id": "user-1",
        "X-Roles": "admin,contract_manager",
    }


@pytest.fixture()
def viewer_headers():
    return {
        "X-Org-Id": ORG_ID,
        "X-User-Id": "user-viewer",
        "X-Roles": "contract_viewer",
    }


@pytest.fixture()
def other_org_headers():
    return {
        "X-Org-Id": OTHER_ORG_ID,
        "X-User-Id": "user-other",
        "X-Roles": "admin,contract_manager",
    }
