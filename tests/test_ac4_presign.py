"""AC4 - the presigned URL expires 5 minutes after it was issued."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

from freezegun import freeze_time

from app.storage.signing import (
    compute_signature,
    is_expired,
    parse_presigned_url,
    verify_presigned_url,
)
from tests.fixtures import PDF_BYTES

SECRET = "test-secret-key"


def _upload(client, headers):
    response = client.post(
        "/api/doc/contracts",
        files={"file": ("contract.pdf", PDF_BYTES, "application/pdf")},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()["contract_id"]


def test_ac4_download_response_has_exactly_two_keys(client, headers):
    """The download response carries exactly ``url`` and ``expires_at``."""
    contract_id = _upload(client, headers)
    response = client.get(f"/api/doc/contracts/{contract_id}/file", headers=headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {"url", "expires_at"}
    assert body["url"].startswith("http")


def test_ac4_expires_parameter_equals_injected_moment_plus_300(client, headers):
    """``X-Amz-Expires`` is 300 and ``expires_at`` is the injected moment + 300."""
    contract_id = _upload(client, headers)
    frozen = datetime(2026, 3, 1, 12, 0, 0, tzinfo=timezone.utc)
    with freeze_time(frozen):
        response = client.get(f"/api/doc/contracts/{contract_id}/file", headers=headers)
    assert response.status_code == 200, response.text
    body = response.json()
    query = parse_qs(urlparse(body["url"]).query)
    assert query["X-Amz-Expires"] == ["300"]
    expected = frozen + timedelta(seconds=300)
    assert body["expires_at"] == expected.isoformat()
    assert parse_presigned_url(body["url"]).expires_at == expected


def test_ac4_url_is_valid_at_299_seconds_and_expired_at_301_seconds(client, headers):
    """The 4:59 / 5:01 pair: still valid at 299 s, expired at 301 s."""
    contract_id = _upload(client, headers)
    response = client.get(f"/api/doc/contracts/{contract_id}/file", headers=headers)
    url = response.json()["url"]
    info = parse_presigned_url(url)
    assert info.expires_in == 300

    still_valid = info.amz_date + timedelta(seconds=299)
    assert is_expired(url, now=still_valid) is False
    ok, reason = verify_presigned_url(url, SECRET, now=still_valid)
    assert ok, reason

    expired = info.amz_date + timedelta(seconds=301)
    assert is_expired(url, now=expired) is True
    ok, reason = verify_presigned_url(url, SECRET, now=expired)
    assert not ok
    assert "expired" in reason


def test_ac4_signature_matches_the_server_side_algorithm(client, headers):
    """The URL carries a genuine SigV4 signature over the object key."""
    contract_id = _upload(client, headers)
    response = client.get(f"/api/doc/contracts/{contract_id}/file", headers=headers)
    url = response.json()["url"]
    info = parse_presigned_url(url)
    assert compute_signature(info, SECRET) == info.signature
    assert verify_presigned_url(url, SECRET)[0] is True
    assert verify_presigned_url(url, "the-wrong-secret")[0] is False


def test_ac4_expires_in_is_a_parameter_default_300(adapter):
    """The expiry is injected, not hard coded."""
    frozen = datetime(2026, 5, 5, 5, 5, 5, tzinfo=timezone.utc)
    with freeze_time(frozen):
        default = adapter.presigned_get_url("contracts/x/2026/05/a.pdf")
        injected = adapter.presigned_get_url("contracts/x/2026/05/a.pdf", expires_in=60)
    assert parse_qs(urlparse(default.url).query)["X-Amz-Expires"] == ["300"]
    assert parse_qs(urlparse(injected.url).query)["X-Amz-Expires"] == ["60"]
    assert default.expires_in == 300
    assert injected.expires_in == 60
