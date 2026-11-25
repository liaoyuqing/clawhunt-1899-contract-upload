"""Generate the real-environment evidence files for order 1899.

Run it against a live MinIO and a live PostgreSQL 16 (see README section 7):

    python scripts/realenv_evidence.py

Every value printed here is produced by talking to the real servers; nothing
is mocked.  The transcripts land in ``evidence/`` and are cited one by one in
``ACCEPTANCE-EVIDENCE.md``.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "evidence"

S3_ENDPOINT = os.environ.get("CONTRACT_TEST_S3_ENDPOINT", "http://127.0.0.1:9000")
S3_SECRET_KEY = os.environ.get("CONTRACT_TEST_S3_SECRET_KEY", "minioadmin")
S3_ACCESS_KEY_ID = os.environ.get("CONTRACT_TEST_S3_ACCESS_KEY_ID", "minioadmin")
DATABASE_URL = os.environ.get(
    "CONTRACT_TEST_DATABASE_URL",
    "postgresql+psycopg://postgres@127.0.0.1:55432/contracts_realenv",
)
BUCKET = os.environ.get("CONTRACT_TEST_BUCKET", "contract-realenv-ac1")
MC = os.environ.get("CONTRACT_TEST_MC", "mc")
RESET_BUCKET = os.environ.get("CONTRACT_TEST_RESET_BUCKET", "1") == "1"


def write(name: str, text: str) -> Path:
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    path = EVIDENCE / name
    path.write_text(text, encoding="utf-8")
    return path


def run(cmd, env=None):
    completed = subprocess.run(
        cmd,
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env={**os.environ, **(env or {})},
    )
    return completed.returncode, (completed.stdout or "") + (completed.stderr or "")


def reset_bucket(store) -> int:
    """Empty the evidence bucket so the transcript shows only this run."""
    if not RESET_BUCKET:
        return 0
    removed = 0
    for key in store.list_keys():
        store.delete_object(key)
        removed += 1
    return removed


def header(title: str) -> str:
    return (
        "# " + title + "\n"
        + "# generated " + datetime.now(timezone.utc).isoformat() + "\n"
        + "# endpoint " + S3_ENDPOINT + "   bucket " + BUCKET + "\n"
        + "# database " + DATABASE_URL + "\n\n"
    )


def adapter():
    sys.path.insert(0, str(ROOT))
    from app.storage.s3_adapter import S3StorageAdapter

    return S3StorageAdapter(
        endpoint=S3_ENDPOINT,
        bucket=BUCKET,
        secret_key=S3_SECRET_KEY,
        access_key_id=S3_ACCESS_KEY_ID,
    )


def postgres_section() -> str:
    from sqlalchemy import create_engine, text

    out = []
    engine = create_engine(DATABASE_URL)
    with engine.connect() as conn:
        out.append("select version() -> " + str(conn.execute(text("select version()")).scalar_one()))
        out.append("current_setting(server_version) -> " + str(conn.execute(text("select current_setting('server_version')")).scalar_one()))
        out.append("")
        out.append("pg_indexes WHERE tablename = 'doc_contract':")
        rows = conn.execute(text(
            "select indexname, indexdef from pg_indexes "
            "where tablename = 'doc_contract' order by indexname"
        )).all()
        for name, definition in rows:
            out.append("  " + name)
            out.append("    " + definition)
        out.append("")
        out.append("information_schema.columns for doc_contract:")
        columns = conn.execute(text(
            "select column_name, data_type, is_nullable from information_schema.columns "
            "where table_name = 'doc_contract' order by ordinal_position"
        )).all()
        for name, data_type, nullable in columns:
            out.append("  " + name + " | " + data_type + " | nullable=" + nullable)
        out.append("")
        out.append("dedup invariant over the whole table:")
        rows = conn.execute(text(
            "select org_id, sha256, count(*) from doc_contract where deleted_at is null "
            "group by org_id, sha256 having count(*) > 1"
        )).all()
        out.append("  active rows = " + str(conn.execute(text(
            "select count(*) from doc_contract where deleted_at is null"
        )).scalar_one()))
        out.append("  distinct orgs = " + str(conn.execute(text(
            "select count(distinct org_id) from doc_contract where deleted_at is null"
        )).scalar_one()))
        out.append("  (org_id, sha256) groups with more than one active row = " + str(len(rows)))
        out.append("  <- 0 means the partial unique index held for every upload this suite made")
    engine.dispose()
    return "\n".join(out) + "\n"


def main() -> int:
    store = adapter()
    removed = reset_bucket(store)
    print("reset evidence bucket " + BUCKET + ": removed " + str(removed) + " object(s)")

    manifest_path = EVIDENCE / "ac1-minio-manifest.json"
    if manifest_path.exists():
        manifest_path.unlink()

    env = {
        "CONTRACT_TEST_S3_ENDPOINT": S3_ENDPOINT,
        "CONTRACT_TEST_S3_SECRET_KEY": S3_SECRET_KEY,
        "CONTRACT_TEST_S3_ACCESS_KEY_ID": S3_ACCESS_KEY_ID,
        "CONTRACT_TEST_DATABASE_URL": DATABASE_URL,
        "CONTRACT_TEST_BUCKET": BUCKET,
        "CONTRACT_TEST_MANIFEST": str(manifest_path),
    }
    targets = (
        ("ac1-minio-upload.txt", ["tests/realenv/test_ac1_minio.py"],
         "AC1 on real MinIO - four formats 201 + head_object ContentLength"),
        ("ac4-presign-expiry.txt", ["tests/realenv/test_ac4_minio.py"],
         "AC4 on real MinIO - 4:59 -> 200, 5:01 -> 403 (MinIO verdict)"),
        ("ac3-pg-tests.txt", ["tests/realenv/test_ac3_postgres.py"],
         "AC3 on real PostgreSQL 16 - dedup, partial index, ten concurrent"),
    )
    failures = 0
    for name, paths, title in targets:
        code, output = run([sys.executable, "-m", "pytest", "-v", "-s"] + paths, env=env)
        command = "python -m pytest -v -s " + " ".join(paths)
        body = header(title) + "$ " + command + "\n" + output + "\nexit code: " + str(code) + "\n"
        if name == "ac1-minio-upload.txt" and manifest_path.exists():
            body += (
                "\n# the manifest the four uploads left behind (one row per allowed format)\n"
                + manifest_path.read_text(encoding="utf-8")
            )
        write(name, body)
        if code != 0:
            failures += 1
            print("FAILED: " + name)

    keys = store.list_keys()

    from tests.realenv.httputil import get

    acl_grants = []
    for grant in store.client.get_bucket_acl(Bucket=BUCKET).get("Grants", []):
        grantee = grant.get("Grantee") or {}
        acl_grants.append({
            "grantee": grantee.get("URI") or grantee.get("ID"),
            "permission": grant.get("Permission"),
        })
    anonymous = ""
    status = error_code = None
    if keys:
        anonymous = S3_ENDPOINT.rstrip("/") + "/" + BUCKET + "/" + keys[0]
        status, error_code, _ = get(anonymous)
    body = header("AC1 on real MinIO - the bucket is private")
    body += "is_public_read() = " + str(store.is_public_read()) + "\n\n"
    body += "bucket ACL grants = " + json.dumps(acl_grants, indent=2) + "\n\n"
    body += "bucket policy = " + json.dumps(store.bucket_policy(), indent=2) + "\n\n"
    body += "anonymous GET " + anonymous + "\n"
    body += "  -> HTTP " + str(status) + ", <Code>" + str(error_code) + "</Code>\n"
    write("ac1-bucket-private.txt", body)

    lines = [header("AC1 on real MinIO - head_object for every object in the bucket")]
    lines.append("objects in bucket: " + str(len(keys)) + "\n\n")
    for key in keys:
        head = store.head_object(key)
        lines.append(json.dumps({
            "object_key": key,
            "ContentLength": head["ContentLength"],
            "ContentType": head.get("ContentType"),
            "ETag": head.get("ETag"),
            "LastModified": str(head.get("LastModified")),
        }, ensure_ascii=False) + "\n")
    write("ac1-minio-head.txt", "".join(lines))

    code, output = run([MC, "ls", "--recursive", "local1899/" + BUCKET])
    write("ac1-minio-mc-ls.txt", header("AC1 on real MinIO - mc ls --recursive")
          + "$ " + MC + " ls --recursive local1899/" + BUCKET + "\n"
          + output + "\nexit code: " + str(code) + "\n")

    alembic_env = {"CONTRACT_DATABASE_URL": DATABASE_URL}
    current_code, current_out = run([sys.executable, "-m", "alembic", "current"], env=alembic_env)
    upgrade_code, upgrade_out = run([sys.executable, "-m", "alembic", "upgrade", "head"], env=alembic_env)
    after_code, after_out = run([sys.executable, "-m", "alembic", "current"], env=alembic_env)
    transcript = header("AC3 on real PostgreSQL 16 - alembic upgrade head")
    transcript += "$ python -m alembic current\n" + current_out
    transcript += "exit code: " + str(current_code) + "\n\n"
    transcript += "$ python -m alembic upgrade head\n" + upgrade_out
    transcript += "exit code: " + str(upgrade_code) + "\n\n"
    transcript += "$ python -m alembic current\n" + after_out
    transcript += "exit code: " + str(after_code) + "\n"
    write("ac3-pg-alembic.txt", transcript)
    if upgrade_code != 0:
        failures += 1

    sys.path.insert(0, str(ROOT))
    write("ac3-pg-index.txt", header("AC3 on real PostgreSQL 16 - index and schema") + postgres_section())

    print("evidence directory:", EVIDENCE)
    for path in sorted(EVIDENCE.glob("*.txt")):
        print("  " + path.name + "  " + str(path.stat().st_size) + " bytes")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())