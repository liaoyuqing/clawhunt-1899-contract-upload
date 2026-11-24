"""Database engine / session plumbing (SQLAlchemy 2.0).

SQLite is the default so the service can be exercised without a PostgreSQL
server; ``CONTRACT_DATABASE_URL`` can point at PostgreSQL 16 instead.  The
schema only uses portable column types, so the partial unique index works on
both engines (``WHERE deleted_at IS NULL``).
"""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from .models import Base


def create_db_engine(database_url: str) -> Engine:
    """Create an engine for ``database_url`` (SQLite or PostgreSQL)."""
    kwargs: dict = {"future": True}
    if database_url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False, "timeout": 30}
    engine = create_engine(database_url, **kwargs)
    if database_url.startswith("sqlite"):
        with engine.connect() as conn:
            conn.exec_driver_sql("PRAGMA journal_mode=WAL")
            conn.exec_driver_sql("PRAGMA busy_timeout=30000")
            conn.commit()
    return engine


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def create_all(engine: Engine) -> None:
    Base.metadata.create_all(engine)
