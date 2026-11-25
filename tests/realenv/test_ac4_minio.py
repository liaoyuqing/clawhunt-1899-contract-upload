"""AC4 on a REAL MinIO server: the server itself refuses the expired URL.

The unit tests in ``tests/test_ac4_presign.py`` check the signature algorithm
and the expiry window with an injected clock; that is a consistency check of
*our* implementation.  This module adds the end-to-end proof the buyer asked
for: the URL is issued by the application with a 300 second lifetime, MinIO
is the only party deciding whether it is still valid, and the observable
result flips from 200 to 403 between 4:59 and 5:01.

How the two moments are produced without waiting five minutes: the signing
clock is frozen with ``freeze_time`` while the URL is ISSUED, then the URL is
fetched with the real clock.  MinIO's verdict depends only on
``X-Amz-Date + X-Amz-Expires`` versus MinIO's own wall clock, so a URL whose
``X-Amz-Date`` is 299 seconds in the past is, from MinIO's point of view,
4:59 old; 301 seconds in the past is 5:01 old.  Nothing about the verdict is
computed in this repository.

The age is measured from the ``X-Amz-Date`` the URL actually carries and
asserted as an exact number, so the 4:59 / 5:01 claim is measured, not
assumed.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

import pytest
from freezegun import freeze_time

from app.storage.signing import parse_presigned_url
from tests.fixtures import PDF_BYTES
from tests.realenv.conftest import requires_real_env
from tests.realenv.httputil import get


def _upload(client, headers) -> str:
    response = client.post(
        "/api/doc/contracts",
        files={"file": ("presign.pdf", PDF_BYTES, "application/pdf")},
        headers=headers,
    )
    assert response.status_code in {201, 409}, response.text
    return response.json()["contract_id"]


def _presign_aged(client, headers, contract_id: str, age_seconds: int):
    """Issue a download URL whose ``X-Amz-Date`` is exactly ``age_seconds`` old.

    ``X-Amz-Date`` has one-second resolution, so the signing moment is frozen at
    a whole second.  The URL is then fetched 0.4 s AFTER the matching second
    boundary, which puts the sampling point a comfortable 0.4 s away from both
    boundaries: the age is ``age_seconds + 0.4``, which truncates to exactly
    ``age_seconds`` and leaves 0.6 s of head room before the verdict could flip
    for timing reasons rather than for policy reasons.

    That margin matters: without it a "4:59" URL could be 5:00 old by the time
    the request reaches MinIO, and the 403 would be correct but the claim
    "still valid just before five minutes" would be untested.
    """
    base = datetime.now(timezone.utc).replace(microsecond=0)
    target = base + timedelta(seconds=0.4)
    if target <= datetime.now(timezone.utc):
        base += timedelta(seconds=1)
        target = base + timedelta(seconds=0.4)
    signed_at = base - timedelta(seconds=age_seconds)

    with freeze_time(signed_at):
        presigned = client.get(
            f"/api/doc/contracts/{contract_id}/file", headers=headers
        )
    assert presigned.status_code == 200, presigned.text
    body = presigned.json()
    assert set(body) == {"url", "expires_at"}
    url = body["url"]
    assert parse_presigned_url(url).amz_date == signed_at

    remaining = (target - datetime.now(timezone.utc)).total_seconds()
    if remaining > 0:
        time.sleep(remaining)

    age = _age_seconds(url)
    assert age == age_seconds, (age, age_seconds)
    return url, body["expires_at"]


def _age_seconds(url: str) -> int:
    return int((datetime.now(timezone.utc) - parse_presigned_url(url).amz_date).total_seconds())


@requires_real_env
def test_ac4_url_still_valid_at_4m59s_on_real_minio(isolated_client, headers):
    """A URL that is 4 minutes 59 seconds old still downloads from MinIO (200)."""
    client, _adapter = isolated_client
    contract_id = _upload(client, headers)
    url, expires_at = _presign_aged(client, headers, contract_id, 299)
    assert parse_presigned_url(url).expires_in == 300
    age = _age_seconds(url)
    assert age == 299, age

    status, error_code, length = get(url)
    assert status == 200, (status, error_code, age)
    assert error_code == ""
    assert length == len(PDF_BYTES), (length, len(PDF_BYTES))
    print(f"age {age}s = 4:59 -> HTTP {status}, {length} bytes, expires_at={expires_at}")


@requires_real_env
def test_ac4_url_expired_at_5m01s_on_real_minio(isolated_client, headers):
    """A URL that is 5 minutes 1 second old is refused by MinIO itself (403)."""
    client, _adapter = isolated_client
    contract_id = _upload(client, headers)
    url, expires_at = _presign_aged(client, headers, contract_id, 301)
    assert parse_presigned_url(url).expires_in == 300
    age = _age_seconds(url)
    assert age == 301, age

    status, error_code, _ = get(url)
    assert status == 403, (status, error_code, age)
    assert error_code == "AccessDenied", error_code
    print(f"age {age}s = 5:01 -> HTTP {status}, code={error_code}, expires_at={expires_at}")


@requires_real_env
def test_ac4_expiry_is_a_server_side_verdict_not_our_check(isolated_client, headers):
    """Fresh URL 200 and stale URL 403 for the same bucket, decided by MinIO."""
    client, _adapter = isolated_client
    contract_id = _upload(client, headers)
    fresh_url, _ = _presign_aged(client, headers, contract_id, 0)
    stale_url, _ = _presign_aged(client, headers, contract_id, 301)

    fresh_status, fresh_code, fresh_len = get(fresh_url)
    stale_status, stale_code, _ = get(stale_url)

    assert fresh_status == 200 and fresh_code == "", (fresh_status, fresh_code)
    assert fresh_len == len(PDF_BYTES)
    assert stale_status == 403 and stale_code == "AccessDenied", (stale_status, stale_code)
    assert "/contract-realenv" in parse_presigned_url(stale_url).canonical_uri