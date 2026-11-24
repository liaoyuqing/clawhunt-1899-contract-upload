"""Contract upload / download business logic."""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, BinaryIO

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from ..auth import AuthContext
from ..config import Settings
from ..errors import StorageError
from ..models import DocContract, new_id
from .dispatch import RecognitionDispatcher, enqueue_dispatch
from .keys import build_object_key
from .streaming import CHUNK_SIZE, UploadTooLargeError, stream_to_object
from .types import (
    ALLOWED_EXTENSIONS,
    UnsupportedMediaTypeError,
    normalize_extension,
    resolve_extension,
)

DB_RETRY_ATTEMPTS = 40
DB_RETRY_DELAY = 0.05


@dataclass
class UploadResult:
    status_code: int
    payload: dict[str, Any]


class ContractService:
    """Implements the two endpoints of order 1899."""

    def __init__(
        self,
        *,
        settings: Settings,
        adapter: Any,
        dispatcher: RecognitionDispatcher,
    ) -> None:
        self.settings = settings
        self.adapter = adapter
        self.dispatcher = dispatcher

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    def _chunks(self, fileobj: BinaryIO) -> Any:
        """Yield the payload in 1 MB chunks - never trust Content-Length."""
        while True:
            chunk = fileobj.read(CHUNK_SIZE)
            if not chunk:
                break
            yield chunk

    def _find_existing(self, session: Session, org_id: str, sha256: str) -> DocContract | None:
        stmt = select(DocContract).where(
            DocContract.org_id == org_id,
            DocContract.sha256 == sha256,
            DocContract.deleted_at.is_(None),
        )
        return session.execute(stmt).scalars().first()

    # ------------------------------------------------------------------
    # upload
    # ------------------------------------------------------------------
    def upload(
        self,
        *,
        session: Session,
        auth: AuthContext,
        filename: str | None,
        fileobj: BinaryIO,
        contract_type_hint: str | None = None,
        member_company_id: str | None = None,
        now: datetime | None = None,
    ) -> UploadResult:
        """Stream the upload, de-duplicate, store the object, create the row.

        Order of operations (this is the core of the order):
        1. reject an unknown extension immediately (415),
        2. stream the payload in chunks - hashing and counting bytes on the
           way, writing the parts into a *multipart* upload so the object
           only becomes visible after step 4,
        3. abort + 413 as soon as the accumulated size exceeds the limit,
        4. verify the magic number (415 on mismatch, still nothing stored),
        5. look up ``(org_id, sha256, deleted_at IS NULL)`` -> 409 with the
           EXISTING contract_id,
        6. only now complete the object at its final key and insert the row.
        """
        ext = normalize_extension(filename)
        if ext is None or ext not in ALLOWED_EXTENSIONS:
            return UploadResult(
                status_code=415,
                payload={
                    "detail": (
                        f"file type is not supported; allowed types: "
                        f"{', '.join(sorted(ALLOWED_EXTENSIONS))}"
                    ),
                    "allowed": sorted(ALLOWED_EXTENSIONS),
                },
            )

        key = build_object_key(
            org_id=auth.org_id,
            ext=ext,
            moment=now,
            site_timezone=self.settings.site_timezone,
        )
        content_type = ALLOWED_EXTENSIONS[ext]

        head_holder: dict[str, bytes] = {}

        def _capture_first_chunk(chunk: bytes) -> None:
            head_holder.setdefault("head", chunk[:8192])

        try:
            outcome = stream_to_object(
                adapter=self.adapter,
                key=key,
                content_type=content_type,
                chunks=self._chunks(fileobj),
                max_size=self.settings.max_file_size,
                chunk_size=CHUNK_SIZE,
                on_first_chunk=_capture_first_chunk,
            )
        except UploadTooLargeError as exc:
            # the multipart upload was aborted -> the bucket keeps no object
            return UploadResult(
                status_code=413,
                payload={
                    "detail": (
                        f"file exceeds the maximum size of {exc.limit} bytes"
                    ),
                    "limit_bytes": exc.limit,
                },
            )
        except StorageError as exc:
            return UploadResult(status_code=502, payload={"detail": str(exc)})

        head = head_holder.get("head", b"")
        try:
            decision = resolve_extension(filename, head)
        except UnsupportedMediaTypeError as exc:
            outcome.writer.abort()
            return UploadResult(
                status_code=415,
                payload={"detail": str(exc), "expected": exc.expected, "actual": exc.actual},
            )

        contract = None
        duplicate = False
        for attempt in range(DB_RETRY_ATTEMPTS):
            try:
                existing = self._find_existing(session, auth.org_id, outcome.sha256)
                if existing is not None:
                    duplicate = True
                    contract = existing
                    break
                contract = DocContract(
                    id=new_id(),
                    org_id=auth.org_id,
                    site_id=auth.org_id,
                    object_key=key,
                    sha256=outcome.sha256,
                    size_bytes=outcome.size,
                    content_type=decision.content_type,
                    ext=decision.ext,
                    original_filename=_safe_filename(filename),
                    contract_type_hint=(contract_type_hint or None),
                    member_company_id=(member_company_id or None),
                    status="uploaded",
                    dispatch_state="dispatch_pending",
                    created_by=auth.user_id,
                )
                session.add(contract)
                session.commit()
                break
            except IntegrityError:
                session.rollback()
                existing = self._find_existing(session, auth.org_id, outcome.sha256)
                if existing is not None:
                    duplicate = True
                    contract = existing
                    break
                if attempt == DB_RETRY_ATTEMPTS - 1:
                    raise
                time.sleep(DB_RETRY_DELAY)
            except OperationalError:
                session.rollback()
                if attempt == DB_RETRY_ATTEMPTS - 1:
                    raise
                time.sleep(DB_RETRY_DELAY)
        
        if duplicate and contract is not None:
            # nothing was written to the bucket - the multipart upload is aborted
            outcome.writer.abort()
            return UploadResult(
                status_code=409,
                payload={"contract_id": contract.id, "status": "duplicate"},
            )

        # the object only becomes visible now - after the de-duplication check
        try:
            outcome.writer.finish()
        except StorageError as exc:
            session.rollback()
            return UploadResult(status_code=502, payload={"detail": str(exc)})

        enqueue_dispatch(session, contract, self.dispatcher)
        session.commit()
        return UploadResult(
            status_code=201,
            payload={"contract_id": contract.id, "status": contract.status},
        )

    # ------------------------------------------------------------------
    # download
    # ------------------------------------------------------------------
    def presign_download(
        self,
        *,
        session: Session,
        auth: AuthContext,
        contract_id: str,
        now: datetime | None = None,
    ) -> UploadResult:
        """Return a presigned download URL for a contract the caller may see."""
        contract = session.execute(
            select(DocContract).where(
                DocContract.id == contract_id,
                DocContract.org_id == auth.org_id,
                DocContract.deleted_at.is_(None),
            )
        ).scalars().first()
        if contract is None:
            # identical for "belongs to another org" and "does not exist"
            return UploadResult(status_code=404, payload={"detail": "contract not found"})
        if not auth.can_view_contracts:
            return UploadResult(
                status_code=403,
                payload={"detail": "the caller has no permission to view this contract"},
            )
        presigned = self.adapter.presigned_get_url(
            contract.object_key,
            expires_in=self.settings.presign_ttl_seconds,
            now=now or datetime.now(timezone.utc),
        )
        return UploadResult(
            status_code=200,
            payload={"url": presigned.url, "expires_at": presigned.expires_at},
        )


def _safe_filename(filename: str | None) -> str | None:
    """Store only the plain file name - never a path."""
    if not filename:
        return None
    base = str(filename).replace("\\", "/").rsplit("/", 1)[-1]
    return base[:512] or None
