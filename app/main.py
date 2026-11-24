"""FastAPI application factory.

The application refuses to START when the mandatory storage configuration is
missing or blank.  The check runs inside the lifespan (start-up), so the
process dies immediately with a clear error instead of serving 500s.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI

from .config import Settings, load_settings
from .db import create_all, create_db_engine, create_session_factory
from .doc.api import contracts_router
from .doc.dispatch import RecognitionDispatcher
from .storage.s3_adapter import S3StorageAdapter


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the application.

    When ``settings`` is omitted the configuration is resolved during
    start-up, which raises :class:`ConfigurationError` for a missing or blank
    endpoint / bucket / secret key.
    """

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        resolved = settings if settings is not None else load_settings()
        engine = create_db_engine(resolved.database_url)
        create_all(engine)
        app.state.engine = engine
        app.state.session_factory = create_session_factory(engine)
        app.state.settings = resolved
        app.state.adapter = S3StorageAdapter(
            endpoint=resolved.endpoint,
            bucket=resolved.bucket,
            secret_key=resolved.secret_key,
            access_key_id=resolved.access_key_id,
            region=resolved.region,
        )
        app.state.dispatcher = RecognitionDispatcher()
        try:
            app.state.adapter.ensure_bucket()
        except Exception:
            # the bucket may be owned by another account - the API still starts
            pass
        yield
        engine.dispose()

    app = FastAPI(
        title="Member Space Platform - Contract Document API",
        version="1.0.0",
        description="Contract file upload and presigned download (order 1899).",
        lifespan=lifespan,
    )
    if settings is not None:
        app.state.settings = settings
    app.state.dispatcher = RecognitionDispatcher()
    app.include_router(contracts_router)

    @app.get("/healthz", include_in_schema=False)
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app


def get_app() -> FastAPI:
    """Entry point for ``uvicorn app.main:get_app --factory``."""
    return create_app()


app = None  # built on start-up by ``uvicorn app.main:get_app --factory``
