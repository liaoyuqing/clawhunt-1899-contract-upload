"""Pure functions that build object keys.

Key rule (order 1899): ``contracts/{org_id}/{yyyy}/{mm}/{uuid4}.{ext}``

* ``yyyy`` / ``mm`` come from the SITE time zone (not the machine time zone)
  so a file uploaded at 23:59:59 on 31 December lands in the right folder.
* ``uuid4`` makes keys unpredictable and collision free.
* ``ext`` comes from the whitelist mapping - it is NEVER sliced off the
  client supplied file name, so ``../../x.pdf`` cannot influence the key.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

DEFAULT_SITE_TIMEZONE = "Asia/Shanghai"
KEY_PREFIX = "contracts"


def site_zoneinfo(site_timezone: str = DEFAULT_SITE_TIMEZONE) -> ZoneInfo:
    return ZoneInfo(site_timezone)


def build_object_key(
    *,
    org_id: str,
    ext: str,
    moment: datetime | None = None,
    site_timezone: str = DEFAULT_SITE_TIMEZONE,
    identifier: str | None = None,
) -> str:
    """Build the object key for an uploaded contract file.

    ``moment`` and ``site_timezone`` are injectable so tests can pin the
    year/month boundary without touching the system clock.
    """
    if not org_id or not str(org_id).strip():
        raise ValueError("org_id must not be blank")
    ext = (ext or "").strip().lower().lstrip(".")
    if not ext:
        raise ValueError("ext must not be blank")
    if moment is None:
        moment = datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    local = moment.astimezone(site_zoneinfo(site_timezone))
    name = identifier if identifier is not None else str(uuid.uuid4())
    return f"{KEY_PREFIX}/{org_id}/{local.year:04d}/{local.month:02d}/{name}.{ext}"


def is_valid_object_key(key: str, org_id: str | None = None) -> bool:
    """Validate the shape of a key produced by :func:`build_object_key`."""
    if not key or key.startswith("/") or ".." in key:
        return False
    parts = key.split("/")
    if len(parts) != 5:
        return False
    prefix, org, year, month, filename = parts
    if prefix != KEY_PREFIX:
        return False
    if org_id is not None and org != org_id:
        return False
    if not (len(year) == 4 and year.isdigit()):
        return False
    if not (len(month) == 2 and month.isdigit() and 1 <= int(month) <= 12):
        return False
    if "." not in filename:
        return False
    stem, ext = filename.rsplit(".", 1)
    try:
        uuid.UUID(stem)
    except (ValueError, AttributeError):
        return False
    return bool(ext) and ext.isascii() and ext.isalnum()
