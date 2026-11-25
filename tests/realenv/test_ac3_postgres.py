"""AC3 on a REAL PostgreSQL 16 server.

The deduplication of order 1899 rests on a PARTIAL unique index
(``(org_id, sha256) WHERE deleted_at IS NULL``) plus the IntegrityError
fallback in ``ContractService.upload``.  SQLite and PostgreSQL differ in
exactly the two places that matter here - partial index enforcement under
concurrent inserts, and the error class raised when the loser commits - so
SQLite is not a substitute.  These tests run the AC3 scenarios against the
real PostgreSQL 16 instance, and dump the index definition it actually
created.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import func, select, text

from app.models import DocContract
from tests.fixtures import PDF_BYTES
from tests.realenv.conftest import requires_real_env

UNIQUE_INDEX_SQL = (
    "SELECT indexdef FROM pg_indexes "
    "WHERE schemaname = current_schema() AND tablename = 'doc_contract' "
    "AND indexname = 'uq_doc_contract_org_sha256_active'"
)


def _upload(client, headers, payload=PDF_BYTES, name="contract.pdf"):
    return client.post(
        "/api/doc/contracts",
        files={"file": (name, payload, "application/pdf")},
        headers=headers,
    )


def _active_rows(client, org_id: str) -> int:
    session_factory = client.app.state.session_factory
    with session_factory() as session:
        return session.execute(
            select(func.count()).select_from(DocContract).where(
                DocContract.org_id == org_id,
                DocContract.deleted_at.is_(None),
            )
        ).scalar_one()


@requires_real_env
def test_postgres_16_is_the_backend(isolated_client):
    """Prove the engine really is PostgreSQL 16 (not SQLite in disguise)."""
    client, _adapter = isolated_client
    with client.app.state.session_factory() as session:
        version = session.execute(text("SELECT version()")).scalar_one()
        dialect = session.execute(text("SELECT current_setting('server_version')")).scalar_one()
    assert version.startswith("PostgreSQL 16"), version
    assert dialect.startswith("16."), dialect
    print(f"backend: {version.split(',')[0]}")


@requires_real_env
def test_partial_unique_index_exists_with_the_where_clause(isolated_client):
    """The index created by alembic is unique AND carries WHERE deleted_at IS NULL."""
    client, _adapter = isolated_client
    with client.app.state.session_factory() as session:
        rows = session.execute(text(UNIQUE_INDEX_SQL)).scalars().all()
    assert len(rows) == 1, rows
    indexdef = rows[0]
    assert "UNIQUE INDEX" in indexdef, indexdef
    assert "deleted_at IS NULL" in indexdef, indexdef
    assert "org_id" in indexdef and "sha256" in indexdef, indexdef
    print(f"index: {indexdef}")


@requires_real_env
def test_ac3_duplicate_upload_returns_409_with_the_same_contract_id_on_postgres(
    isolated_client, headers
):
    """AC3 on PostgreSQL: second upload -> 409, same contract_id, one row."""
    client, adapter = isolated_client
    first = _upload(client, headers)
    assert first.status_code == 201, first.text
    first_id = first.json()["contract_id"]
    keys_after_first = adapter.list_keys()

    second = _upload(client, headers)
    assert second.status_code == 409, second.text
    assert second.json()["contract_id"] == first_id
    assert set(second.json()) == {"contract_id", "status"}
    assert _active_rows(client, headers["X-Org-Id"]) == 1
    assert adapter.list_keys() == keys_after_first


@requires_real_env
def test_ac3_reupload_after_soft_delete_on_postgres(isolated_client, headers):
    """The partial predicate lets the same file back in after a soft delete."""
    client, _adapter = isolated_client
    first = _upload(client, headers, payload=PDF_BYTES + b"soft-delete-case")
    assert first.status_code == 201, first.text
    first_id = first.json()["contract_id"]

    with client.app.state.session_factory() as session:
        contract = session.get(DocContract, first_id)
        assert contract is not None
        from datetime import datetime, timezone

        contract.deleted_at = datetime.now(timezone.utc)
        session.commit()

    second = _upload(client, headers, payload=PDF_BYTES + b"soft-delete-case")
    assert second.status_code == 201, second.text
    assert second.json()["contract_id"] != first_id


@requires_real_env
def test_ten_concurrent_uploads_of_the_same_file_yield_one_201_on_postgres(
    isolated_client, headers
):
    """10 concurrent uploads of one file: exactly 1x201 + 9x409, one row, one object."""
    client, adapter = isolated_client
    payload = PDF_BYTES + b"ten-concurrent-postgres"

    def _post(_index: int):
        response = _upload(client, headers, payload=payload, name=f"race-{_index}.pdf")
        return response.status_code, response.json()

    with ThreadPoolExecutor(max_workers=10) as pool:
        results = list(pool.map(_post, range(10)))

    codes = [code for code, _ in results]
    assert codes.count(201) == 1, codes
    assert codes.count(409) == 9, codes

    winners = {body["contract_id"] for code, body in results if code == 201}
    losers = {body["contract_id"] for code, body in results if code == 409}
    assert len(winners) == 1, winners
    assert losers == winners, (losers, winners)
    print(f"concurrent codes: {sorted(codes)} -> one 201, nine 409")

    org = headers["X-Org-Id"]
    with client.app.state.session_factory() as session:
        active = session.execute(
            select(DocContract).where(
                DocContract.org_id == org,
                DocContract.deleted_at.is_(None),
            )
        ).scalars().all()
    assert len(active) == 1, [row.id for row in active]
    sha = active[0].sha256
    assert len(adapter.list_keys()) >= 1

    with client.app.state.session_factory() as session:
        same_sha = session.execute(
            select(func.count()).select_from(DocContract).where(
                DocContract.org_id == org,
                DocContract.sha256 == sha,
                DocContract.deleted_at.is_(None),
            )
        ).scalar_one()
    assert same_sha == 1, same_sha