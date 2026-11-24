"""Recognition-task dispatch stub plus the outbox that retries it.

Contract of this module (documented on purpose):
* the record and its outbox row are written FIRST,
* the dispatch to the recognition queue happens AFTER, through a stub,
* a failing dispatch NEVER rolls back the upload: the contract switches to
  ``dispatch_pending`` and the API still answers 201,
* the outbox row carries the idempotency key ``(contract_id, dispatch_version)``
  so a retry can never create a second recognition task.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..errors import DispatchError
from ..models import DocContract, DocContractOutbox, DocRecognitionTask


@dataclass
class DispatchResult:
    delivered: bool
    task_id: str | None = None
    error: str | None = None


@dataclass
class RecognitionDispatcher:
    """Stub of the recognition queue client.

    ``fail`` flips the stub into the failing mode used by the tests.
    """

    fail: bool = False
    calls: list[dict[str, Any]] = field(default_factory=list)

    def dispatch(self, payload: dict[str, Any]) -> str:
        self.calls.append(dict(payload))
        if self.fail:
            raise DispatchError("recognition queue unavailable")
        return "task-" + str(payload.get("contract_id", "unknown"))


def idempotency_key(contract_id: str, dispatch_version: int) -> str:
    return f"{contract_id}:{dispatch_version}"


def enqueue_dispatch(
    session: Session,
    contract: DocContract,
    dispatcher: RecognitionDispatcher,
    *,
    dispatch_version: int = 1,
) -> DispatchResult:
    """Write the outbox row, then try to deliver the recognition task."""
    key = idempotency_key(contract.id, dispatch_version)
    existing = session.execute(
        select(DocContractOutbox).where(DocContractOutbox.idempotency_key == key)
    ).scalar_one_or_none()
    if existing is None:
        existing = DocContractOutbox(
            org_id=contract.org_id,
            contract_id=contract.id,
            dispatch_version=dispatch_version,
            idempotency_key=key,
            payload=json.dumps(
                {
                    "contract_id": contract.id,
                    "org_id": contract.org_id,
                    "object_key": contract.object_key,
                    "sha256": contract.sha256,
                },
                ensure_ascii=False,
            ),
            state="pending",
            attempts=0,
        )
        session.add(existing)
        session.flush()
    else:
        existing.state = "pending"
        existing.attempts = (existing.attempts or 0) + 1
    contract.dispatch_state = "dispatch_pending"
    session.flush()

    try:
        external_id = dispatcher.dispatch(json.loads(existing.payload))
    except DispatchError as exc:
        existing.state = "pending"
        existing.last_error = str(exc)
        contract.dispatch_state = "dispatch_pending"
        session.flush()
        return DispatchResult(delivered=False, error=str(exc))

    task = session.execute(
        select(DocRecognitionTask).where(DocRecognitionTask.contract_id == contract.id)
    ).scalar_one_or_none()
    if task is None:
        task = DocRecognitionTask(
            org_id=contract.org_id,
            contract_id=contract.id,
            dispatch_version=dispatch_version,
            status="queued",
            payload=json.dumps(
                {"external_id": external_id, "object_key": contract.object_key},
                ensure_ascii=False,
            ),
        )
        session.add(task)
        session.flush()
    existing.state = "sent"
    existing.last_error = None
    contract.dispatch_state = "dispatched"
    session.flush()
    return DispatchResult(delivered=True, task_id=task.id)


def retry_pending_dispatch(
    session: Session,
    dispatcher: RecognitionDispatcher,
    *,
    limit: int = 100,
) -> list[DispatchResult]:
    """Retry every pending outbox row (used by the background worker)."""
    rows = session.execute(
        select(DocContractOutbox)
        .where(DocContractOutbox.state == "pending")
        .order_by(DocContractOutbox.created_at)
        .limit(limit)
    ).scalars().all()
    results: list[DispatchResult] = []
    for row in rows:
        contract = session.get(DocContract, row.contract_id)
        if contract is None:
            continue
        row.attempts = (row.attempts or 0) + 1
        try:
            external_id = dispatcher.dispatch(json.loads(row.payload))
        except DispatchError as exc:
            row.state = "pending"
            row.last_error = str(exc)
            contract.dispatch_state = "dispatch_pending"
            session.flush()
            results.append(DispatchResult(delivered=False, error=str(exc)))
            continue
        task = session.execute(
            select(DocRecognitionTask).where(DocRecognitionTask.contract_id == row.contract_id)
        ).scalar_one_or_none()
        if task is None:
            task = DocRecognitionTask(
                org_id=row.org_id,
                contract_id=row.contract_id,
                dispatch_version=row.dispatch_version,
                status="queued",
                payload=json.dumps(
                    {"external_id": external_id, "object_key": contract.object_key},
                    ensure_ascii=False,
                ),
            )
            session.add(task)
            session.flush()
        row.state = "sent"
        row.last_error = None
        contract.dispatch_state = "dispatched"
        session.flush()
        results.append(DispatchResult(delivered=True, task_id=task.id))
    return results
