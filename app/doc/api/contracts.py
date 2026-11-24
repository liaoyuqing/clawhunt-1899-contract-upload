"""The two HTTP endpoints of order 1899.

* ``POST /api/doc/contracts`` - multipart upload (file + 2 optional fields).
* ``GET  /api/doc/contracts/{contract_id}/file`` - presigned download URL.

Both responses carry EXACTLY two keys so no internal detail leaks:
* upload -> ``{"contract_id", "status"}``
* download -> ``{"url", "expires_at"}``
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Form, UploadFile, Response, status
from fastapi.responses import JSONResponse

from ...auth import AuthContext
from ...deps import get_adapter, get_auth, get_dispatcher, get_session, get_settings
from ..service import ContractService

router = APIRouter(prefix="/api/doc", tags=["contracts"])


@router.post(
    "/contracts",
    status_code=status.HTTP_201_CREATED,
    summary="Upload a contract file (PDF / DOCX / JPG / PNG, max 20 MB)",
    response_description="contract_id and status",
    responses={
        201: {"description": "file stored"},
        403: {"description": "the caller has no upload permission"},
        409: {"description": "the same file already exists in this organisation"},
        413: {"description": "the file exceeds the maximum size"},
        415: {"description": "the file type is not supported"},
    },
)
async def upload_contract(
    file: Annotated[UploadFile, File(description="the contract file itself")],
    contract_type_hint: Annotated[
        str | None,
        Form(description="optional hint: new / renewal / supplement"),
    ] = None,
    member_company_id: Annotated[
        str | None,
        Form(description="optional member company id"),
    ] = None,
    auth: Annotated[AuthContext, Depends(get_auth)] = None,
    session: Annotated[Any, Depends(get_session)] = None,
    adapter: Annotated[Any, Depends(get_adapter)] = None,
    dispatcher: Annotated[Any, Depends(get_dispatcher)] = None,
    settings: Annotated[Any, Depends(get_settings)] = None,
) -> Response:
    """Stream the upload into the private bucket and create the contract."""
    if not auth.can_upload_contracts:
        return JSONResponse(
            status_code=403,
            content={"detail": "the caller has no permission to upload contracts"},
        )
    service = ContractService(
        settings=settings, adapter=adapter, dispatcher=dispatcher
    )
    fileobj = file.file
    try:
        result = service.upload(
            session=session,
            auth=auth,
            filename=file.filename,
            fileobj=fileobj,
            contract_type_hint=contract_type_hint,
            member_company_id=member_company_id,
            now=datetime.now(timezone.utc),
        )
    finally:
        try:
            fileobj.seek(0)
        except Exception:
            pass
    if result.status_code == 201:
        return JSONResponse(status_code=201, content=result.payload)
    return JSONResponse(status_code=result.status_code, content=result.payload)


@router.get(
    "/contracts/{contract_id}/file",
    summary="Return a short lived presigned download URL",
    response_description="url and expires_at",
    responses={
        200: {"description": "presigned url"},
        403: {"description": "the caller has no permission to view this contract"},
        404: {"description": "the contract does not exist in this organisation"},
    },
)
async def download_contract(
    contract_id: str,
    auth: Annotated[AuthContext, Depends(get_auth)] = None,
    session: Annotated[Any, Depends(get_session)] = None,
    adapter: Annotated[Any, Depends(get_adapter)] = None,
    dispatcher: Annotated[Any, Depends(get_dispatcher)] = None,
    settings: Annotated[Any, Depends(get_settings)] = None,
) -> Response:
    service = ContractService(
        settings=settings, adapter=adapter, dispatcher=dispatcher
    )
    result = service.presign_download(
        session=session,
        auth=auth,
        contract_id=contract_id,
        now=datetime.now(timezone.utc),
    )
    return JSONResponse(status_code=result.status_code, content=result.payload)
