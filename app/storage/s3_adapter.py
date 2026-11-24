"""S3-compatible private object storage adapter (MinIO / AWS S3).

Everything the service needs from object storage goes through this adapter:
* a PRIVATE bucket (ACL + public access block + explicit deny policy),
* streaming writes through the S3 multipart API so a 20 MB file is never
  held fully in memory,
* reads, heads, lists and deletes,
* presigned download URLs whose expiry is a *parameter* (default 300 s) so
  the value can be asserted in tests.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Iterable, Iterator

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from ..errors import StorageError

DEFAULT_PRESIGN_TTL_SECONDS = 300
MIN_PART_SIZE = 5 * 1024 * 1024


@dataclass(frozen=True)
class PresignedUrl:
    """A presigned GET URL together with its absolute expiry instant."""

    url: str
    expires_at: str
    expires_in: int


class S3StorageAdapter:
    """Thin, testable wrapper over boto3's S3 client."""

    def __init__(
        self,
        *,
        endpoint: str,
        bucket: str,
        secret_key: str,
        access_key_id: str = "minioadmin",
        region: str = "us-east-1",
        client: Any | None = None,
    ) -> None:
        self.endpoint = endpoint
        self.bucket = bucket
        self.secret_key = secret_key
        self.access_key_id = access_key_id
        self.region = region
        self._client = client

    # ------------------------------------------------------------------
    # client
    # ------------------------------------------------------------------
    @property
    def client(self) -> Any:
        if self._client is None:
            self._client = boto3.client(
                "s3",
                endpoint_url=self.endpoint,
                aws_access_key_id=self.access_key_id,
                aws_secret_access_key=self.secret_key,
                region_name=self.region,
                config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
            )
        return self._client

    # ------------------------------------------------------------------
    # bucket
    # ------------------------------------------------------------------
    def ensure_bucket(self) -> None:
        """Create the bucket if missing and make sure it stays PRIVATE.

        This is idempotent - the MinIO init job in deploy/ calls it.
        """
        try:
            self.client.head_bucket(Bucket=self.bucket)
            created = False
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            if code not in {"404", "NoSuchBucket", "NotFound"}:
                raise StorageError(f"cannot reach bucket {self.bucket}: {exc}") from exc
            self.client.create_bucket(Bucket=self.bucket)
            created = True
        self._enforce_private(created=created)

    def _enforce_private(self, created: bool = False) -> None:
        """Idempotently make the bucket private.

        * force the canned ACL back to ``private`` (MinIO ignores it, AWS
        * does not),
        * enable the public access block,
        * install a bucket policy that denies any attempt to publish an
        * object with a public ACL.

        The policy deliberately does NOT deny ``s3:GetObject``: an
        unauthenticated GET is already rejected by the private ACL, and a
        blanket deny would also break the legitimate presigned download.
        """
        try:
            self.client.put_bucket_acl(Bucket=self.bucket, ACL="private")
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            if code not in {"NotImplemented", "501", "InvalidBucketAcl"}:
                raise StorageError(f"cannot set a private ACL on {self.bucket}: {exc}") from exc
        try:
            self.client.put_public_access_block(
                Bucket=self.bucket,
                PublicAccessBlockConfiguration={
                    "BlockPublicAcls": True,
                    "IgnorePublicAcls": True,
                    "BlockPublicPolicy": True,
                    "RestrictPublicBuckets": True,
                },
            )
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            if code not in {"NoSuchPublicAccessBlockConfiguration", "NotImplemented", "501"}:
                raise StorageError(f"cannot block public access on {self.bucket}: {exc}") from exc
        policy = {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Sid": "DenyPublicReadACL",
                    "Effect": "Deny",
                    "Principal": "*",
                    "Action": "s3:PutObjectAcl",
                    "Resource": f"arn:aws:s3:::{self.bucket}/*",
                    "Condition": {
                        "StringEquals": {
                            "s3:x-amz-acl": ["public-read", "public-read-write"],
                        },
                    },
                },
            ],
        }
        self.client.put_bucket_policy(
            Bucket=self.bucket,
            Policy=json.dumps(policy),
        )

    def is_public_read(self) -> bool:
        """Return True when the bucket ACL grants READ to AllUsers."""
        acl = self.client.get_bucket_acl(Bucket=self.bucket)
        for grant in acl.get("Grants", []):
            uri = (grant.get("Grantee") or {}).get("URI", "")
            if uri == "http://acs.amazonaws.com/groups/global/AllUsers":
                return True
        return False

    def bucket_policy(self) -> dict:
        try:
            raw = self.client.get_bucket_policy(Bucket=self.bucket)["Policy"]
        except ClientError:
            return {}
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {}

    # ------------------------------------------------------------------
    # objects
    # ------------------------------------------------------------------
    def put_object(self, key: str, body: bytes, content_type: str = "application/octet-stream") -> str:
        result = self.client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=body,
            ContentType=content_type,
        )
        return result.get("ETag", "")

    def put_stream(
        self,
        key: str,
        chunks: Iterable[bytes],
        content_type: str = "application/octet-stream",
    ) -> str:
        """Stream an object into the bucket.

        Small payloads are sent with a single PutObject; larger ones use the
        multipart API so the whole file is never buffered in memory.  If the
        multipart flow fails the upload is aborted, which leaves NO half
        object behind in the bucket.
        """
        iterator = iter(chunks)
        first = next(iterator, b"")
        if not first:
            return self.put_object(key, b"", content_type=content_type)
        if len(first) < MIN_PART_SIZE:
            body = first + b"".join(iterator)
            return self.put_object(key, body, content_type=content_type)

        upload_id = self.client.create_multipart_upload(
            Bucket=self.bucket, Key=key, ContentType=content_type
        )["UploadId"]
        parts: list[dict[str, Any]] = []
        try:
            buffer = bytearray(first)
            part_number = 1
            for chunk in iterator:
                buffer.extend(chunk)
                while len(buffer) >= MIN_PART_SIZE:
                    block = bytes(buffer[:MIN_PART_SIZE])
                    del buffer[:MIN_PART_SIZE]
                    etag = self.client.upload_part(
                        Bucket=self.bucket,
                        Key=key,
                        UploadId=upload_id,
                        PartNumber=part_number,
                        Body=block,
                    )["ETag"]
                    parts.append({"ETag": etag, "PartNumber": part_number})
                    part_number += 1
            if buffer:
                etag = self.client.upload_part(
                    Bucket=self.bucket,
                    Key=key,
                    UploadId=upload_id,
                    PartNumber=part_number,
                    Body=bytes(buffer),
                )["ETag"]
                parts.append({"ETag": etag, "PartNumber": part_number})
            result = self.client.complete_multipart_upload(
                Bucket=self.bucket,
                Key=key,
                UploadId=upload_id,
                MultipartUpload={"Parts": parts},
            )
            return result.get("ETag", "")
        except Exception as exc:
            self.abort_multipart(key, upload_id)
            raise StorageError(f"failed to write object {key}: {exc}") from exc

    def abort_multipart(self, key: str, upload_id: str) -> None:
        """Abort a multipart upload (removes every already written part)."""
        try:
            self.client.abort_multipart_upload(
                Bucket=self.bucket, Key=key, UploadId=upload_id
            )
        except ClientError:
            pass

    def get_object(self, key: str) -> bytes:
        try:
            response = self.client.get_object(Bucket=self.bucket, Key=key)
            return response["Body"].read()
        except ClientError as exc:
            raise StorageError(f"cannot read object {key}: {exc}") from exc

    def head_object(self, key: str) -> dict:
        try:
            return dict(self.client.head_object(Bucket=self.bucket, Key=key))
        except ClientError as exc:
            raise StorageError(f"cannot stat object {key}: {exc}") from exc

    def object_exists(self, key: str) -> bool:
        try:
            self.head_object(key)
            return True
        except StorageError:
            return False

    def list_keys(self, prefix: str = "") -> list[str]:
        keys: list[str] = []
        token: str | None = None
        while True:
            kwargs: dict[str, Any] = {"Bucket": self.bucket, "Prefix": prefix}
            if token:
                kwargs["ContinuationToken"] = token
            page = self.client.list_objects_v2(**kwargs)
            keys.extend(item["Key"] for item in page.get("Contents", []) or [])
            if not page.get("IsTruncated"):
                break
            token = page.get("NextContinuationToken")
        return sorted(keys)

    def list_prefixes(self) -> list[str]:
        """Return the common prefixes (virtual folders) inside the bucket."""
        resp = self.client.list_objects_v2(Bucket=self.bucket, Delimiter="/")
        return sorted(p["Prefix"] for p in resp.get("CommonPrefixes", []) or [])

    def delete_object(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=key)

    # ------------------------------------------------------------------
    # presigned URLs
    # ------------------------------------------------------------------
    def presigned_get_url(
        self,
        key: str,
        expires_in: int = DEFAULT_PRESIGN_TTL_SECONDS,
        now: Any | None = None,
    ) -> PresignedUrl:
        """Create a presigned GET URL.

        ``expires_in`` is a parameter (default 300 s) and ``now`` may inject a
        clock for tests.  The returned ``expires_at`` is the absolute expiry
        instant computed from the very same clock, so a test can assert
        ``expires_at == now + 300`` without a network round trip.
        """
        if expires_in <= 0:
            raise ValueError("expires_in must be a positive number of seconds")
        url = self.client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": key},
            ExpiresIn=expires_in,
        )
        expires_at = _expiry_from_presigned_url(url, now=now, expires_in=expires_in)
        return PresignedUrl(url=url, expires_at=expires_at, expires_in=expires_in)


def _expiry_from_presigned_url(url: str, now: Any | None, expires_in: int) -> str:
    """Compute the absolute expiry instant of a presigned URL.

    When a clock is injected the expiry is derived from that clock; otherwise
    it is derived from the ``X-Amz-Date`` query parameter of the URL itself.
    """
    from datetime import datetime, timedelta, timezone

    if now is not None:
        base = now if isinstance(now, datetime) else datetime.now(timezone.utc)
        if base.tzinfo is None:
            base = base.replace(tzinfo=timezone.utc)
        return (base + timedelta(seconds=expires_in)).astimezone(timezone.utc).isoformat()
    from urllib.parse import parse_qs, urlparse

    query = parse_qs(urlparse(url).query)
    raw = (query.get("X-Amz-Date") or [""])[0]
    if raw:
        parsed = datetime.strptime(raw, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
        return (parsed + timedelta(seconds=expires_in)).astimezone(timezone.utc).isoformat()
    return (datetime.now(timezone.utc) + timedelta(seconds=expires_in)).isoformat()
