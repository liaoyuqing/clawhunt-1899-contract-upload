"""Key generation: shape, time zone, uniqueness."""

from __future__ import annotations

from datetime import datetime, timezone

from app.doc.keys import build_object_key, is_valid_object_key


def test_key_shape_matches_the_contract():
    key = build_object_key(org_id="org-1", ext="pdf")
    assert key.startswith("contracts/org-1/")
    assert key.endswith(".pdf")
    assert is_valid_object_key(key, org_id="org-1")


def test_key_uses_the_site_timezone_not_utc():
    """23:59:59 in Shanghai on 31 December is still the old year."""
    moment = datetime(2025, 12, 31, 15, 59, 59, tzinfo=timezone.utc)
    key = build_object_key(
        org_id="org-1", ext="pdf", moment=moment, site_timezone="Asia/Shanghai"
    )
    assert "/2025/12/" in key

    moment = datetime(2025, 12, 31, 16, 0, 1, tzinfo=timezone.utc)
    key = build_object_key(
        org_id="org-1", ext="pdf", moment=moment, site_timezone="Asia/Shanghai"
    )
    assert "/2026/01/" in key


def test_key_crosses_the_month_boundary():
    moment = datetime(2026, 4, 30, 16, 0, 0, tzinfo=timezone.utc)
    key = build_object_key(
        org_id="org-1", ext="pdf", moment=moment, site_timezone="Asia/Shanghai"
    )
    assert "/2026/05/" in key


def test_1000_generated_keys_are_unique():
    """1000 keys, no collision."""
    keys = {build_object_key(org_id="org-1", ext="pdf") for _ in range(1000)}
    assert len(keys) == 1000
    for key in keys:
        assert is_valid_object_key(key, org_id="org-1")


def test_key_never_contains_the_client_file_name():
    key = build_object_key(org_id="org-1", ext="pdf")
    assert ".." not in key
    assert "/" not in key.split("/")[-1].replace(".pdf", "")
