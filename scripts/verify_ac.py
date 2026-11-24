"""Run the four acceptance criteria one after another and print PASS / FAIL.

Usage::

    python scripts/verify_ac.py

Exit code 0 = all four acceptance criteria pass, 1 = at least one failed.
The script drives the SAME pytest nodes that are documented in
``ACCEPTANCE-EVIDENCE.md``; it does not re-implement the checks.
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# make the Chinese acceptance texts print correctly on a Windows console
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

ACCEPTANCE = [
    (
        "AC1",
        "上传 4 种允许格式均返回 201，并能在 MinIO 中看到对应对象",
        [
            "tests/test_ac1_formats.py::test_ac1_each_allowed_format_returns_201[pdf]",
            "tests/test_ac1_formats.py::test_ac1_each_allowed_format_returns_201[docx]",
            "tests/test_ac1_formats.py::test_ac1_each_allowed_format_returns_201[jpg]",
            "tests/test_ac1_formats.py::test_ac1_each_allowed_format_returns_201[png]",
            "tests/test_ac1_formats.py::test_ac1_bucket_is_not_public_read",
        ],
    ),
    (
        "AC2",
        "上传 21 MB 文件返回 413，上传 .exe 返回 415",
        [
            "tests/test_ac2_limits.py::test_ac2_21mb_is_rejected_with_413",
            "tests/test_ac2_limits.py::test_ac2_exe_is_rejected_with_415",
            "tests/test_ac2_limits.py::test_ac2_exe_renamed_to_pdf_is_rejected_with_415",
            "tests/test_ac2_limits.py::test_ac2_pdf_content_with_png_extension_is_rejected",
            "tests/test_ac2_limits.py::test_boundary_exactly_20mb_is_accepted",
            "tests/test_ac2_limits.py::test_boundary_20mb_plus_one_byte_is_rejected",
            "tests/test_ac2_limits.py::test_413_leaves_no_object_and_no_pending_multipart",
            "tests/test_ac2_limits.py::test_content_length_lie_is_ignored",
        ],
    ),
    (
        "AC3",
        "同一文件重复上传返回 409，body 中 contract_id 与首次一致",
        [
            "tests/test_ac3_duplicates.py::test_ac3_duplicate_upload_returns_409_with_the_same_contract_id",
            "tests/test_ac3_duplicates.py::test_ac3_duplicate_in_another_org_is_allowed",
            "tests/test_ac3_duplicates.py::test_ac3_reupload_after_soft_delete_creates_a_new_contract",
        ],
    ),
    (
        "AC4",
        "预签名地址超过 5 分钟后失效（冻结时间的单元测试证明）",
        [
            "tests/test_ac4_presign.py::test_ac4_download_response_has_exactly_two_keys",
            "tests/test_ac4_presign.py::test_ac4_expires_parameter_equals_injected_moment_plus_300",
            "tests/test_ac4_presign.py::test_ac4_url_is_valid_at_299_seconds_and_expired_at_301_seconds",
            "tests/test_ac4_presign.py::test_ac4_signature_matches_the_server_side_algorithm",
            "tests/test_ac4_presign.py::test_ac4_expires_in_is_a_parameter_default_300",
        ],
    ),
]


def main() -> int:
    failures = 0
    for code, text, nodes in ACCEPTANCE:
        print(f"=== {code}: {text} ===")
        started = time.perf_counter()
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", "-v", "--no-header", *nodes],
            cwd=ROOT,
        )
        elapsed = time.perf_counter() - started
        if proc.returncode == 0:
            print(f"{code} PASS  ({len(nodes)} node(s), {elapsed:.2f}s)")
        else:
            failures += 1
            print(f"{code} FAIL  ({len(nodes)} node(s), {elapsed:.2f}s, exit={proc.returncode})")
        print()
    if failures:
        print(f"{failures} acceptance criterion/criteria FAILED")
        return 1
    print("all four acceptance criteria PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
