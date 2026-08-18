"""SQLite engine, schema, FTS5 knowledge index, and session helpers."""

from collections.abc import Generator
from datetime import UTC, datetime

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import StaticPool


class Base(DeclarativeBase):
    pass


def utcnow() -> datetime:
    """Timezone-aware UTC now, used as the default for created_at / updated_at."""
    return datetime.now(UTC)


@event.listens_for(Engine, "connect")
def _sqlite_enable_foreign_keys(dbapi_connection, _connection_record) -> None:
    """SQLite does not enforce FKs unless this PRAGMA is set per connection."""
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def create_db_engine(database_url: str) -> Engine:
    kwargs: dict = {"future": True}
    connect_args: dict = {}
    if database_url.startswith("sqlite"):
        connect_args["check_same_thread"] = False  # FastAPI and tests share the engine
        connect_args["timeout"] = 30  # wait if the dashboard and agent write at once
        if ":memory:" in database_url:
            kwargs["poolclass"] = StaticPool  # keep one in-memory DB across connections
    return create_engine(database_url, connect_args=connect_args, **kwargs)


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
