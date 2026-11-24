"""AWS Signature Version 4 helpers for presigned S3 URLs.

The object store validates a presigned URL on the SERVER: it recomputes the
signature and compares the signature date plus the expiry window against
its own clock.  MinIO is not available on the delivery machine (no docker),
so this module re-implements exactly that rule so the behaviour can be
proven locally and in CI:

* :func:`verify_presigned_url` recomputes the SigV4 signature of a presigned
  GET URL and checks the expiry window against an injectable clock.

The rule is the one documented by AWS: the request is valid while
``now < X-Amz-Date + X-Amz-Expires`` (the expiry instant itself is
exclusive).
"""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Mapping
from urllib.parse import parse_qsl, quote, urlparse

ALGORITHM = "AWS4-HMAC-SHA256"
UNSIGNED_PAYLOAD = "UNSIGNED-PAYLOAD"


@dataclass(frozen=True)
class PresignedInfo:
    url: str
    method: str
    host: str
    canonical_uri: str
    query: dict[str, str]
    signed_headers: str
    signature: str
    amz_date: datetime
    expires_in: int

    @property
    def expires_at(self) -> datetime:
        return self.amz_date + timedelta(seconds=self.expires_in)


def parse_presigned_url(url: str) -> PresignedInfo:
    """Split a presigned URL into its SigV4 components."""
    parsed = urlparse(url)
    query = {key: value for key, value in parse_qsl(parsed.query, keep_blank_values=True)}
    amz_date_raw = query.get("X-Amz-Date")
    if not amz_date_raw:
        raise ValueError("presigned URL has no X-Amz-Date parameter")
    expires_raw = query.get("X-Amz-Expires")
    if expires_raw is None:
        raise ValueError("presigned URL has no X-Amz-Expires parameter")
    signature = query.get("X-Amz-Signature")
    if not signature:
        raise ValueError("presigned URL has no X-Amz-Signature parameter")
    credential = query.get("X-Amz-Credential", "")
    scope_parts = credential.split("/")
    if len(scope_parts) < 5:
        raise ValueError("presigned URL has a malformed X-Amz-Credential")
    return PresignedInfo(
        url=url,
        method="GET",
        host=parsed.netloc,
        canonical_uri=parsed.path or "/",
        query=query,
        signed_headers=query.get("X-Amz-SignedHeaders", "host"),
        signature=signature,
        amz_date=datetime.strptime(amz_date_raw, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc),
        expires_in=int(expires_raw),
    )


def _sign(key: bytes, message: str) -> bytes:
    return hmac.new(key, message.encode("utf-8"), hashlib.sha256).digest()


def _signing_key(secret_key: str, date_stamp: str, region: str, service: str) -> bytes:
    k_date = _sign(f"AWS4{secret_key}".encode("utf-8"), date_stamp)
    k_region = _sign(k_date, region)
    k_service = _sign(k_region, service)
    return _sign(k_service, "aws4_request")


def _canonical_query(query: Mapping[str, str], drop: set[str]) -> str:
    items = [
        (key, value)
        for key, value in query.items()
        if key not in drop
    ]
    items.sort()
    return "&".join(
        f"{quote(key, safe='-_.~')}={quote(value, safe='-_.~')}"
        for key, value in items
    )


def _header_value(info: PresignedInfo, name: str) -> str:
    """Return the value of a signed header.

    ``host`` is not part of the query string - it comes from the URL.  Every
    other signed header of a presigned GET (x-amz-*, content-type, ...) is
    carried inside the query string.
    """
    if name.lower() == "host":
        return info.host
    return info.query.get(name, info.query.get(name.lower(), ""))


def compute_signature(
    info: PresignedInfo,
    secret_key: str,
    *,
    region: str = "us-east-1",
    service: str = "s3",
) -> str:
    """Recompute the SigV4 signature of a presigned GET URL."""
    credential = info.query.get("X-Amz-Credential", "")
    scope = credential.split("/")[1:]
    date_stamp, region_from_url, service_from_url = scope[0], scope[1], scope[2]
    region = region_from_url or region
    service = service_from_url or service

    canonical_headers = "".join(
        f"{name}:{_header_value(info, name)}\n"
        for name in sorted(info.signed_headers.split(";"))
        if name
    )
    canonical_request = "\n".join(
        [
            info.method,
            info.canonical_uri,
            _canonical_query(info.query, {"X-Amz-Signature"}),
            canonical_headers,
            info.signed_headers,
            UNSIGNED_PAYLOAD,
        ]
    )
    scope_string = "/".join([date_stamp, region, service, "aws4_request"])
    string_to_sign = "\n".join(
        [
            ALGORITHM,
            info.amz_date.strftime("%Y%m%dT%H%M%SZ"),
            scope_string,
            hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
        ]
    )
    signing_key = _signing_key(secret_key, date_stamp, region, service)
    return hmac.new(
        signing_key, string_to_sign.encode("utf-8"), hashlib.sha256
    ).hexdigest()


def verify_presigned_url(
    url: str,
    secret_key: str,
    *,
    now: datetime | None = None,
    region: str = "us-east-1",
    service: str = "s3",
) -> tuple[bool, str]:
    """Validate a presigned URL the way the object store would.

    Returns ``(ok, reason)``.  ``ok`` is True only when the signature
    matches AND the expiry window still contains ``now``.
    """
    try:
        info = parse_presigned_url(url)
    except ValueError as exc:
        return False, str(exc)
    expected = compute_signature(info, secret_key, region=region, service=service)
    if not hmac.compare_digest(expected, info.signature):
        return False, "signature does not match"
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    if current >= info.expires_at:
        return False, f"signature expired at {info.expires_at.isoformat()}"
    return True, "valid"


def is_expired(url: str, now: datetime | None = None) -> bool:
    """Return True when the expiry window of ``url`` has elapsed."""
    info = parse_presigned_url(url)
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current >= info.expires_at
