"""AC3 - the same file twice -> 409 with the SAME contract_id."""

from __future__ import annotations

from sqlalchemy import func, select

from app.models import DocContract
from tests.conftest import ORG_ID
from tests.fixtures import PDF_BYTES


def _upload(client, headers, payload=PDF_BYTES, name="contract.pdf"):
    return client.post(
        "/api/doc/contracts",
        files={"file": (name, payload, "application/pdf")},
        headers=headers,
    )


def test_ac3_duplicate_upload_returns_409_with_the_same_contract_id(
    client, headers, adapter
):
    """AC3: the second upload returns 409 and the FIRST contract_id."""
    first = _upload(client, headers)
    assert first.status_code == 201, first.text
    first_id = first.json()["contract_id"]
    keys_after_first = adapter.list_keys()
    assert len(keys_after_first) == 1

    second = _upload(client, headers)
    assert second.status_code == 409, second.text
    body = second.json()
    assert body["contract_id"] == first_id
    assert set(body) == {"contract_id", "status"}

    # the duplicate must not create a second row nor a second object
    with client.app.state.session_factory() as session:
        count = session.execute(
            select(func.count()).select_from(DocContract).where(
                DocContract.org_id == ORG_ID,
                DocContract.deleted_at.is_(None),
            )
        ).scalar_one()
    assert count == 1, count
    assert adapter.list_keys() == keys_after_first


def test_ac3_duplicate_in_another_org_is_allowed(client, headers, other_org_headers, adapter):
    """The de-duplication is scoped to the organisation."""
    first = _upload(client, headers)
    assert first.status_code == 201
    second = _upload(client, other_org_headers)
    assert second.status_code == 201, second.text
    assert second.json()["contract_id"] != first.json()["contract_id"]
    assert len(adapter.list_keys()) == 2


def test_ac3_reupload_after_soft_delete_creates_a_new_contract(client, headers, adapter):
    """After a soft delete the same file may be uploaded again (new id)."""
    first = _upload(client, headers)
    assert first.status_code == 201
    first_id = first.json()["contract_id"]

    app = client.app
    with app.state.session_factory() as session:
        contract = session.get(DocContract, first_id)
        assert contract is not None
        from datetime import datetime, timezone

        contract.deleted_at = datetime.now(timezone.utc)
        session.commit()

    second = _upload(client, headers)
    assert second.status_code == 201, second.text
    second_id = second.json()["contract_id"]
    assert second_id != first_id

    with app.state.session_factory() as session:
        active = session.execute(
            select(func.count()).select_from(DocContract).where(
                DocContract.org_id == ORG_ID,
                DocContract.deleted_at.is_(None),
            )
        ).scalar_one()
    assert active == 1
