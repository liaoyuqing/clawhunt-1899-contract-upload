"""Dispatch semantics: a failing stub still answers 201 and queues a retry."""

from __future__ import annotations

from sqlalchemy import func, select

from app.doc.dispatch import idempotency_key, retry_pending_dispatch
from app.models import DocContract, DocContractOutbox, DocRecognitionTask
from tests.conftest import ORG_ID
from tests.fixtures import PDF_BYTES


def _upload(client, headers):
    response = client.post(
        "/api/doc/contracts",
        files={"file": ("contract.pdf", PDF_BYTES, "application/pdf")},
        headers=headers,
    )
    return response


def test_failing_dispatch_still_returns_201_and_queues_the_outbox(
    client, headers, dispatcher
):
    """A broken recognition queue must not fail the upload."""
    dispatcher.fail = True
    response = _upload(client, headers)
    assert response.status_code == 201, response.text
    body = response.json()
    assert set(body) == {"contract_id", "status"}
    contract_id = body["contract_id"]

    with client.app.state.session_factory() as session:
        contract = session.get(DocContract, contract_id)
        assert contract is not None
        assert contract.status == "uploaded"
        assert contract.dispatch_state == "dispatch_pending"
        outbox = session.execute(
            select(DocContractOutbox).where(DocContractOutbox.contract_id == contract_id)
        ).scalars().all()
        assert len(outbox) == 1
        assert outbox[0].state == "pending"
        assert outbox[0].idempotency_key == idempotency_key(contract_id, 1)


def test_retry_after_a_failure_creates_exactly_one_recognition_task(
    client, headers, dispatcher
):
    """The outbox retry delivers the task exactly once."""
    dispatcher.fail = True
    response = _upload(client, headers)
    assert response.status_code == 201
    contract_id = response.json()["contract_id"]

    dispatcher.fail = False
    with client.app.state.session_factory() as session:
        results = retry_pending_dispatch(session, dispatcher)
        assert len(results) == 1, results
        assert results[0].delivered is True
        session.commit()

    with client.app.state.session_factory() as session:
        tasks = session.execute(
            select(DocRecognitionTask).where(DocRecognitionTask.contract_id == contract_id)
        ).scalars().all()
        assert len(tasks) == 1, len(tasks)
        outbox = session.execute(
            select(DocContractOutbox).where(DocContractOutbox.contract_id == contract_id)
        ).scalars().all()
        assert len(outbox) == 1
        assert outbox[0].state == "sent"
        contract = session.get(DocContract, contract_id)
        assert contract.dispatch_state == "dispatched"

        # a second retry must not create another task (idempotency key)
        retry_pending_dispatch(session, dispatcher)
        session.commit()
        again = session.execute(
            select(func.count()).select_from(DocRecognitionTask).where(
                DocRecognitionTask.contract_id == contract_id
            )
        ).scalar_one()
    assert again == 1, again


def test_successful_dispatch_creates_one_task_and_one_outbox_row(client, headers, dispatcher):
    """The happy path also records the task and the outbox."""
    response = _upload(client, headers)
    assert response.status_code == 201
    contract_id = response.json()["contract_id"]
    with client.app.state.session_factory() as session:
        tasks = session.execute(
            select(DocRecognitionTask).where(DocRecognitionTask.contract_id == contract_id)
        ).scalars().all()
        outbox = session.execute(
            select(DocContractOutbox).where(DocContractOutbox.contract_id == contract_id)
        ).scalars().all()
    assert len(tasks) == 1
    assert len(outbox) == 1
    assert outbox[0].state == "sent"
