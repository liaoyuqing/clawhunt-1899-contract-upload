"""AC1 - all four allowed formats return 201 and land in the bucket."""

from __future__ import annotations

import re

import pytest

from app.doc.keys import is_valid_object_key
from tests.conftest import ORG_ID
from tests.fixtures import SAMPLE_FILES

KEY_PATTERN = re.compile(
    r"^contracts/[A-Za-z0-9_-]+/\d{4}/\d{2}/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\.[a-z0-9]+$"
)


@pytest.mark.parametrize("ext", ["pdf", "docx", "jpg", "png"])
def test_ac1_each_allowed_format_returns_201(client, headers, adapter, ext):
    """AC1: every allowed format -> 201, object visible in the bucket."""
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

    after = adapter.list_keys()
    new_keys = set(after) - before
    assert len(new_keys) == 1, new_keys
    key = new_keys.pop()
    assert KEY_PATTERN.match(key), key
    assert is_valid_object_key(key, org_id=ORG_ID), key
    assert key.endswith("." + ext), key
    assert adapter.object_exists(key)
    assert adapter.head_object(key)["ContentLength"] == len(payload)


def test_ac1_bucket_is_not_public_read(client, headers, adapter):
    """AC1: the bucket must not grant public read."""
    assert adapter.is_public_read() is False
    policy = adapter.bucket_policy()
    statements = policy.get("Statement", [])
    assert statements, policy
    for statement in statements:
        if statement.get("Effect") == "Allow" and statement.get("Principal") == "*":
            pytest.fail(f"bucket policy allows anonymous access: {statement}")
