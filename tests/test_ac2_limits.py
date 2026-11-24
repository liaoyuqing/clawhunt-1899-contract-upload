"""AC2 - 21 MB -> 413, unsupported type -> 415."""

from __future__ import annotations

import io

import pytest

from tests.fixtures import EXE_BYTES, PDF_BYTES, PNG_BYTES

MB = 1024 * 1024
PDF_PREFIX = b"%PDF-1.7\n"


def _pdf_of_size(total: int) -> bytes:
    """Build a PDF-looking payload of exactly ``total`` bytes."""
    assert total >= len(PDF_PREFIX)
    return PDF_PREFIX + b"A" * (total - len(PDF_PREFIX))


def _upload(client, headers, name, payload, content_type="application/octet-stream"):
    return client.post(
        "/api/doc/contracts",
        files={"file": (name, payload, content_type)},
        headers=headers,
    )


def test_ac2_21mb_is_rejected_with_413(client, headers, adapter):
    """AC2: a 21 MB file is refused with 413."""
    payload = _pdf_of_size(21 * MB)
    assert len(payload) == 21 * MB
    before = set(adapter.list_keys())
    response = _upload(client, headers, "big.pdf", payload)
    assert response.status_code == 413, response.text
    after = set(adapter.list_keys())
    assert after == before, "a rejected upload must not leave an object behind"


def test_ac2_exe_is_rejected_with_415(client, headers, adapter):
    """AC2: an .exe file is refused with 415."""
    before = set(adapter.list_keys())
    response = _upload(client, headers, "virus.exe", EXE_BYTES)
    assert response.status_code == 415, response.text
    assert set(adapter.list_keys()) == before


def test_ac2_exe_renamed_to_pdf_is_rejected_with_415(client, headers, adapter):
    """AC2: an .exe renamed to .pdf is refused (magic number wins)."""
    before = set(adapter.list_keys())
    response = _upload(client, headers, "virus.pdf", EXE_BYTES)
    assert response.status_code == 415, response.text
    assert set(adapter.list_keys()) == before


def test_ac2_pdf_content_with_png_extension_is_rejected(client, headers, adapter):
    """AC2: PDF content wearing a .png extension is refused with 415."""
    before = set(adapter.list_keys())
    response = _upload(client, headers, "fake.png", PDF_BYTES)
    assert response.status_code == 415, response.text
    assert set(adapter.list_keys()) == before


def test_boundary_exactly_20mb_is_accepted(client, headers, adapter):
    """Boundary: exactly 20 MB is accepted."""
    payload = _pdf_of_size(20 * MB)
    assert len(payload) == 20 * MB
    response = _upload(client, headers, "exact.pdf", payload)
    assert response.status_code == 201, response.text
    keys = adapter.list_keys()
    assert len(keys) == 1
    assert adapter.head_object(keys[0])["ContentLength"] == 20 * MB


def test_boundary_20mb_plus_one_byte_is_rejected(client, headers, adapter):
    """Boundary: 20 MB + 1 byte is refused with 413."""
    payload = _pdf_of_size(20 * MB + 1)
    assert len(payload) == 20 * MB + 1
    before = set(adapter.list_keys())
    response = _upload(client, headers, "over.pdf", payload)
    assert response.status_code == 413, response.text
    assert set(adapter.list_keys()) == before


def test_413_leaves_no_object_and_no_pending_multipart(client, headers, adapter):
    """A 413 must not leave a half object or a pending multipart upload."""
    payload = _pdf_of_size(21 * MB)
    response = _upload(client, headers, "leftover.pdf", payload)
    assert response.status_code == 413
    assert adapter.list_keys() == []
    pending = adapter.client.list_multipart_uploads(Bucket=adapter.bucket).get("Uploads")
    assert not pending, pending


def test_content_length_lie_is_ignored(client, headers, adapter):
    """The Content-Length header is never trusted."""
    payload = _pdf_of_size(21 * MB)
    assert len(payload) == 21 * MB
    body = _multipart_body("liar.pdf", payload, contract_type_hint="new")
    response = client.post(
        "/api/doc/contracts",
        content=body,
        headers={**headers, "Content-Type": "multipart/form-data; boundary=BOUNDARY"},
    )
    assert response.status_code == 413, response.text
    assert adapter.list_keys() == []


def _multipart_body(filename: str, payload: bytes, contract_type_hint: str = "new") -> bytes:
    """Build a multipart body but LIE about the size in the part header."""
    head = (
        f"--BOUNDARY\r\n"
        f"Content-Disposition: form-data; name=\"contract_type_hint\"\r\n\r\n"
        f"{contract_type_hint}\r\n"
        f"--BOUNDARY\r\n"
        f"Content-Disposition: form-data; name=\"file\"; filename=\"{filename}\"\r\n"
        f"Content-Type: application/pdf\r\n\r\n"
    ).encode("utf-8")
    tail = b"\r\n--BOUNDARY--\r\n"
    return head + payload + tail
