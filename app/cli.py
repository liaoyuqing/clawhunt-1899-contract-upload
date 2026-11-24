"""Small helper CLI: initialise the bucket and print its privacy state."""

from __future__ import annotations

import json

from .config import load_settings
from .storage.s3_adapter import S3StorageAdapter


def main() -> int:
    settings = load_settings()
    adapter = S3StorageAdapter(
        endpoint=settings.endpoint,
        bucket=settings.bucket,
        secret_key=settings.secret_key,
        access_key_id=settings.access_key_id,
        region=settings.region,
    )
    adapter.ensure_bucket()
    print(
        json.dumps(
            {
                "bucket": settings.bucket,
                "endpoint": settings.endpoint,
                "public_read": adapter.is_public_read(),
                "policy_statements": len(adapter.bucket_policy().get("Statement", [])),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
