"""Ten concurrent uploads of the SAME file -> exactly one 201."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import func, select

from app.models import DocContract
from tests.conftest import ORG_ID
from tests.fixtures import PDF_BYTES


def test_ten_concurrent_uploads_of_the_same_file_yield_one_201(client, headers, adapter):
    """Only one concurrent upload wins, the others get 409."""

    def _post(_index: int):
        response = client.post(
            "/api/doc/contracts",
            files={"file": ("contract.pdf", PDF_BYTES, "application/pdf")},
            headers=headers,
        )
        return response.status_code, response.json()

    with ThreadPoolExecutor(max_workers=10) as pool:
        results = list(pool.map(_post, range(10)))

    codes = [code for code, _ in results]
    assert codes.count(201) == 1, codes
    assert codes.count(409) == 9, codes

    ids = {body["contract_id"] for code, body in results if code == 201}
    conflict_ids = {body["contract_id"] for code, body in results if code == 409}
    assert len(ids) == 1, ids
    assert conflict_ids == ids, (conflict_ids, ids)

    with client.app.state.session_factory() as session:
        count = session.execute(
            select(func.count()).select_from(DocContract).where(
                DocContract.org_id == ORG_ID,
                DocContract.deleted_at.is_(None),
            )
        ).scalar_one()
    assert count == 1, count
    assert len(adapter.list_keys()) == 1, adapter.list_keys()
