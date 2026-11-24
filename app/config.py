"""Start-up configuration for the contract document service.

Design rules (order 1899):
* The object-storage endpoint, bucket name and secret key are MANDATORY.
* They are read from environment variables ONLY - never from a file, never
  from a default that silently points at production.
* A missing variable AND an empty/blank string are both rejected, and the
  rejection happens at START-UP (import of :mod:`app.main`), not as a 500
  at request time.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from .errors import ConfigurationError

ENV_ENDPOINT = "CONTRACT_OBJECT_STORAGE_ENDPOINT"
ENV_BUCKET = "CONTRACT_OBJECT_STORAGE_BUCKET"
ENV_SECRET_KEY = "CONTRACT_OBJECT_STORAGE_SECRET_KEY"
ENV_ACCESS_KEY_ID = "CONTRACT_OBJECT_STORAGE_ACCESS_KEY_ID"
ENV_REGION = "CONTRACT_OBJECT_STORAGE_REGION"
ENV_DATABASE_URL = "CONTRACT_DATABASE_URL"
ENV_SITE_TZ = "CONTRACT_SITE_TIMEZONE"
ENV_MAX_FILE_SIZE = "CONTRACT_MAX_FILE_SIZE_BYTES"
ENV_PRESIGN_TTL = "CONTRACT_PRESIGN_TTL_SECONDS"

REQUIRED_ENV_VARS = (ENV_ENDPOINT, ENV_BUCKET, ENV_SECRET_KEY)


def _require(env: dict[str, str], name: str) -> str:
    """Return a non-blank environment value or raise :class:`ConfigurationError`."""
    if name not in env:
        raise ConfigurationError(
            f"missing required environment variable {name}; "
            "object storage endpoint/bucket/secret key must be provided by the environment"
        )
    value = env[name]
    if value is None or not str(value).strip():
        raise ConfigurationError(
            f"environment variable {name} is present but blank; "
            "an empty string is not a valid configuration value"
        )
    return str(value).strip()


@dataclass(frozen=True)
class Settings:
    """Validated runtime configuration."""

    endpoint: str
    bucket: str
    secret_key: str
    access_key_id: str
    region: str
    database_url: str
    site_timezone: str
    max_file_size: int
    presign_ttl_seconds: int

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "Settings":
        env = dict(os.environ if env is None else env)
        endpoint = _require(env, ENV_ENDPOINT)
        bucket = _require(env, ENV_BUCKET)
        secret_key = _require(env, ENV_SECRET_KEY)
        access_key_id = (env.get(ENV_ACCESS_KEY_ID) or "minioadmin").strip()
        region = (env.get(ENV_REGION) or "us-east-1").strip()
        database_url = (env.get(ENV_DATABASE_URL) or "sqlite:///./contracts.db").strip()
        site_timezone = (env.get(ENV_SITE_TZ) or "Asia/Shanghai").strip()
        max_file_size = int(env.get(ENV_MAX_FILE_SIZE) or 20 * 1024 * 1024)
        presign_ttl = int(env.get(ENV_PRESIGN_TTL) or 300)
        return cls(
            endpoint=endpoint,
            bucket=bucket,
            secret_key=secret_key,
            access_key_id=access_key_id,
            region=region,
            database_url=database_url,
            site_timezone=site_timezone,
            max_file_size=max_file_size,
            presign_ttl_seconds=presign_ttl,
        )


def load_settings(env: dict[str, str] | None = None) -> Settings:
    """Load settings or raise :class:`ConfigurationError` (called at start-up)."""
    return Settings.from_env(env)
