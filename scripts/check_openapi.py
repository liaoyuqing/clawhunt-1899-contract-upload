"""Assert the exported OpenAPI document describes the contract endpoints.

Usage::

    python scripts/check_openapi.py

Exit code 0 = every assertion holds, 1 = at least one assertion failed.
The document is written to ``docs/openapi.json`` as evidence.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import Settings  # noqa: E402
from app.main import create_app  # noqa: E402

UPLOAD_PATH = "/api/doc/contracts"
DOWNLOAD_PATH = "/api/doc/contracts/{contract_id}/file"


def build_openapi() -> dict:
    """Build the OpenAPI document of the application."""
    settings = Settings(
        endpoint="http://127.0.0.1:9000",
        bucket="contract-bucket",
        secret_key="openapi-check",
        access_key_id="openapi-check",
        region="us-east-1",
        database_url="sqlite:///:memory:",
        site_timezone="Asia/Shanghai",
        max_file_size=20 * 1024 * 1024,
        presign_ttl_seconds=300,
    )
    return create_app(settings).openapi()


def resolve(document: dict, schema: dict) -> dict:
    """Resolve a local ``$ref`` against ``components/schemas``."""
    ref = schema.get("$ref")
    if not ref or not ref.startswith("#/"):
        return schema
    node: object = document
    for part in ref[2:].split("/"):
        node = (node or {}).get(part, {})  # type: ignore[assignment]
    return node if isinstance(node, dict) else schema


def check(document: dict) -> list[str]:
    """Return the list of problems; an empty list means everything is fine."""
    problems: list[str] = []
    paths = document.get("paths", {})

    upload = paths.get(UPLOAD_PATH, {}).get("post")
    if upload is None:
        problems.append(f"{UPLOAD_PATH} POST is missing")
    else:
        content = (upload.get("requestBody") or {}).get("content") or {}
        if "multipart/form-data" not in content:
            problems.append(
                "the upload requestBody does not declare multipart/form-data"
            )
        else:
            schema = resolve(document, content["multipart/form-data"].get("schema") or {})
            properties = schema.get("properties") or {}
            if "file" not in properties:
                problems.append("the multipart body does not declare the file part")
            for optional in ("contract_type_hint", "member_company_id"):
                if optional not in properties:
                    problems.append(
                        f"the multipart body does not declare the optional field {optional}"
                    )
            required = schema.get("required") or []
            if "file" not in required:
                problems.append("the file part must be required")
            for optional in ("contract_type_hint", "member_company_id"):
                if optional in required:
                    problems.append(f"{optional} must stay optional")
        responses = upload.get("responses") or {}
        for code in ("201", "403", "409", "413", "415"):
            if code not in responses:
                problems.append(f"the upload does not declare the response {code}")

    download = paths.get(DOWNLOAD_PATH, {}).get("get")
    if download is None:
        problems.append(f"{DOWNLOAD_PATH} GET is missing")
    else:
        download_responses = download.get("responses") or {}
        for code in ("200", "403", "404"):
            if code not in download_responses:
                problems.append(f"the download does not declare the response {code}")

    return problems


def main() -> int:
    document = build_openapi()
    problems = check(document)
    out = ROOT / "docs" / "openapi.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(document, indent=2, ensure_ascii=False), encoding="utf-8")
    if problems:
        print("openapi checks FAILED:")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print("openapi checks passed")
    print("  upload  /api/doc/contracts: requestBody multipart/form-data with file,",
          "contract_type_hint, member_company_id")
    print("  upload  responses: 201, 403, 409, 413, 415")
    print("  download /api/doc/contracts/{contract_id}/file: responses 200, 403, 404")
    print(f"  document written to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
