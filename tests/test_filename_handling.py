"""The client file name must never influence the object key."""

from __future__ import annotations

from app.doc.keys import is_valid_object_key
from tests.conftest import ORG_ID
from tests.fixtures import PDF_BYTES


def test_path_traversal_file_name_still_yields_a_valid_key(client, headers, adapter):
    """``../../x.pdf`` is accepted and produces a well formed key."""
    response = client.post(
        "/api/doc/contracts",
        files={"file": ("../../x.pdf", PDF_BYTES, "application/pdf")},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    keys = adapter.list_keys()
    assert len(keys) == 1
    key = keys[0]
    assert ".." not in key
    assert is_valid_object_key(key, org_id=ORG_ID)
    assert key.endswith(".pdf")


def test_non_ascii_file_name_yields_a_valid_ascii_key(client, headers, adapter):
    """A Chinese file name is accepted; the key stays ASCII."""
    response = client.post(
        "/api/doc/contracts",
        files={"file": ("合同扫描件.pdf", PDF_BYTES, "application/pdf")},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    keys = adapter.list_keys()
    assert len(keys) == 1
    key = keys[0]
    assert key.isascii()
    assert is_valid_object_key(key, org_id=ORG_ID)


def test_file_name_without_extension_is_rejected_with_415(client, headers, adapter):
    """A file without an extension cannot be typed -> 415."""
    response = client.post(
        "/api/doc/contracts",
        files={"file": ("contract", PDF_BYTES, "application/pdf")},
        headers=headers,
    )
    assert response.status_code == 415, response.text
    assert adapter.list_keys() == []
