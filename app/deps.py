"""FastAPI dependencies (settings, storage, database, identity)."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import Depends, Header, Request
from sqlalchemy.orm import Session

from .auth import AuthContext, parse_roles


def get_settings(request: Request) -> Any:
    return request.app.state.settings


def get_adapter(request: Request) -> Any:
    return request.app.state.adapter


def get_dispatcher(request: Request) -> Any:
    return request.app.state.dispatcher


def get_session(request: Request) -> Any:
    factory = request.app.state.session_factory
    session = factory()
    try:
        yield session
    finally:
        session.close()


def get_auth(
    x_org_id: Annotated[str, Header(alias="X-Org-Id")],
    x_user_id: Annotated[str, Header(alias="X-User-Id")] = "anonymous",
    x_roles: Annotated[str, Header(alias="X-Roles")] = "",
) -> AuthContext:
    """Resolve the caller identity (mocked S2-IAM)."""
    return AuthContext(
        org_id=x_org_id,
        user_id=x_user_id,
        roles=parse_roles(x_roles),
    )


SettingsDep = Annotated[Any, Depends(get_settings)]
AdapterDep = Annotated[Any, Depends(get_adapter)]
DispatcherDep = Annotated[Any, Depends(get_dispatcher)]
SessionDep = Annotated[Session, Depends(get_session)]
AuthDep = Annotated[AuthContext, Depends(get_auth)]
