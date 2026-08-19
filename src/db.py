"""SQLite engine, schema, FTS5 knowledge index, and session helpers."""

import time
from collections.abc import Callable, Generator
from datetime import UTC, datetime
from typing import TypeVar

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import StaticPool

T = TypeVar("T")


class Base(DeclarativeBase):
    pass


def utcnow() -> datetime:
    """Timezone-aware UTC now, used as the default for created_at / updated_at."""
    return datetime.now(UTC)


def retry_on_lock(
    operation: Callable[[], T],
    *,
    attempts: int = 4,
    delay: float = 0.5,
    on_retry: Callable[[], None] | None = None,
) -> T:
    """Retry ``operation`` when SQLite reports a transient write lock."""
    for attempt in range(attempts):
        try:
            return operation()
        except OperationalError as exc:
            if "database is locked" in str(exc) and attempt < attempts - 1:
                if on_retry is not None:
                    on_retry()
                time.sleep(delay * (attempt + 1))
                continue
            raise


@event.listens_for(Engine, "connect")
def _sqlite_enable_foreign_keys(dbapi_connection, _connection_record) -> None:
    """SQLite does not enforce FKs unless this PRAGMA is set per connection."""
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.close()


def create_db_engine(database_url: str) -> Engine:
    kwargs: dict = {"future": True}
    connect_args: dict = {}
    if database_url.startswith("sqlite"):
        connect_args["check_same_thread"] = False  # FastAPI and tests share the engine
        connect_args["timeout"] = 60
        if ":memory:" in database_url:
            kwargs["poolclass"] = StaticPool  # keep one in-memory DB across connections
    engine = create_engine(database_url, connect_args=connect_args, **kwargs)
    if database_url.startswith("sqlite") and ":memory:" not in database_url:
        with engine.connect() as conn:
            conn.exec_driver_sql("PRAGMA journal_mode=WAL")
    return engine


def init_fts(engine: Engine) -> None:
    """Create the FTS5 virtual table used by knowledge search."""
    with engine.begin() as conn:
        conn.exec_driver_sql(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_fts USING fts5(
                article_id UNINDEXED,
                title,
                body
            )
            """
        )


def create_schema(engine: Engine) -> None:
    from src import models as _models  # noqa: F401  # register tables on Base.metadata

    Base.metadata.create_all(engine)
    init_fts(engine)


def drop_schema(engine: Engine) -> None:
    from src import models as _models  # noqa: F401  # register tables on Base.metadata

    with engine.begin() as conn:
        conn.exec_driver_sql("DROP TABLE IF EXISTS knowledge_fts")
    Base.metadata.drop_all(engine)


def session_factory(engine: Engine) -> sessionmaker[Session]:
    """Session maker that does not expire objects on commit (dashboard reuses them)."""
    return sessionmaker(
        bind=engine, autoflush=False, expire_on_commit=False, future=True
    )


def session_scope(factory: sessionmaker[Session]) -> Generator[Session, None, None]:
    """Commit on success, roll back on error, always close."""
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
