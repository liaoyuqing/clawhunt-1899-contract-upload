"""AC1 on a REAL MinIO server.

Order 1899 acceptance criterion 1 says the four allowed formats must return 201
AND the object must be visible *in MinIO*.  The default suite proves it against
moto; this module proves it against the real server, and leaves a manifest so
``mc ls --recursive`` / ``head_object`` output can be attached as evidence.

The four format uploads go into the evidence bucket, so ``mc ls`` shows exactly
those four objects.  The anonymity check uses its own throw-away bucket, so it
cannot pollute that listing.
"""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

import pytest

from app.doc.keys import is_valid_object_key
from tests.fixtures import SAMPLE_FILES
from tests.realenv.conftest import requires_real_env
from tests.realenv.httputil import get

MANIFEST = Path(
    os.environ.get("CONTRACT_TEST_MANIFEST") or "evidence/ac1-minio-manifest.json"
)


@pytest.fixture(scope="module")
def manifest():
    """Collect one row per uploaded format, then dump it for the report."""
    rows: list[dict] = []
    yield rows
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps(rows, indent=2), encoding="utf-8")


@requires_real_env
@pytest.mark.parametrize("ext", ["pdf", "docx", "jpg", "png"])
def test_ac1_each_allowed_format_returns_201_on_real_minio(
    real_client, headers, manifest, ext
):
    """Every allowed format -> 201, and head_object sees the exact byte count."""
    client, adapter = real_client
    filename, payload = SAMPLE_FILES[ext]
    before = set(adapter.list_keys())
    response = client.post(
        "/api/doc/contracts",
        files={"file": (filename, payload, "application/octet-stream")},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert set(body) == {"contract_id", "status"}
    assert body["status"] == "uploaded"

    new_keys = set(adapter.list_keys()) - before
    assert len(new_keys) == 1, new_keys
    key = new_keys.pop()
    assert key.endswith("." + ext), key
    assert is_valid_object_key(key, org_id=headers["X-Org-Id"]), key
    assert adapter.object_exists(key)
    head = adapter.head_object(key)
    assert head["ContentLength"] == len(payload), (head["ContentLength"], len(payload))

    manifest.append(
        {
            "format": ext,
            "status_code": response.status_code,
            "contract_id": body["contract_id"],
            "object_key": key,
            "upload_bytes": len(payload),
            "minio_content_length": head["ContentLength"],
            "bucket": adapter.bucket,
        }
    )


@requires_real_env
def test_ac1_bucket_is_not_public_read_on_real_minio(open_client, headers):
    """The bucket stays private: no AllUsers grant, no anonymous Allow, anon GET 403."""
    bucket = "contract-realenv-private-%s" % uuid.uuid4().hex[:8]
    client, _app, adapter = open_client(bucket)
    assert adapter.is_public_read() is False
    policy = adapter.bucket_policy()
    for statement in policy.get("Statement", []) or []:
        if statement.get("Effect") == "Allow":
            principal = statement.get("Principal")
            assert principal not in {"*", {"AWS": ["*"]}}, statement

    _filename, payload = SAMPLE_FILES["pdf"]
    response = client.post(
        "/api/doc/contracts",
        files={"file": ("private-check.pdf", payload, "application/pdf")},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    keys = adapter.list_keys()
    assert len(keys) == 1, keys
    anonymous_url = "%s/%s/%s" % (adapter.endpoint.rstrip("/"), adapter.bucket, keys[0])
    status, error_code, _ = get(anonymous_url)
    assert status == 403, (status, anonymous_url)
    assert error_code == "AccessDenied", error_code


@requires_real_env
def test_ac1_manifest_covers_all_four_formats(real_client, manifest):
    """The evidence manifest must end up with exactly the four formats."""
    seen = {row["format"] for row in manifest}
    assert seen == {"pdf", "docx", "jpg", "png"}, seen
    for row in manifest:
        assert row["status_code"] == 201
        assert row["minio_content_length"] == row["upload_bytes"]