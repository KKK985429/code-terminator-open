from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.pool import QueuePool, StaticPool

from services.shared.settings import database_url


Base = declarative_base()
engine: Engine | None = None
SessionLocal: sessionmaker | None = None


def _build_engine(url: str) -> Engine:
    if url.startswith("sqlite"):
        is_memory = url in {"sqlite://", "sqlite:///:memory:"} or "mode=memory" in url
        kwargs = {"connect_args": {"check_same_thread": False}}
        if is_memory:
            kwargs["poolclass"] = StaticPool
        return create_engine(url, **kwargs)
    return create_engine(
        url,
        poolclass=QueuePool,
        pool_size=10,
        max_overflow=20,
        pool_pre_ping=True,
        pool_recycle=3600,
    )


def configure_database(url: str | None = None) -> Engine:
    global engine, SessionLocal
    target = url or database_url()
    if engine is not None:
        engine.dispose()
    engine = _build_engine(target)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    return engine


def ensure_database() -> Engine:
    if engine is None:
        return configure_database()
    return engine


def init_database() -> None:
    from services.shared import models  # noqa: F401

    Base.metadata.create_all(bind=ensure_database())


def reset_database() -> None:
    from services.shared import models  # noqa: F401

    Base.metadata.drop_all(bind=ensure_database())
    Base.metadata.create_all(bind=ensure_database())


def get_db() -> Generator:
    if SessionLocal is None:
        configure_database()
    assert SessionLocal is not None
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


configure_database()
