"""Shared pytest fixtures: isolated SQLite, demo seed data, and a FakeLLM HTTP client."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy.orm import Session, sessionmaker
from starlette.testclient import TestClient

from src.config import Settings
from src.db import create_db_engine, create_schema
from src.llm.fake import FakeLLM
from src.seed import seed_from_fixtures
from src.web.app import create_app

# Knowledge articles and demo.json live in the repo, not in each test's tmp_path DB.
REPO_DATA = Path(__file__).resolve().parents[1] / "data"


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """Point the app at a throwaway SQLite file so tests never touch the demo database."""
    return Settings(
        openai_api_key="test-not-used",
        openai_model="fake",
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        auto_remediate=True,
        data_dir=str(REPO_DATA),
    )


@pytest.fixture
def engine(settings: Settings):
    """Create ORM tables and the FTS5 knowledge index for this test's database."""
    engine = create_db_engine(settings.database_url)
    create_schema(engine)
    return engine


@pytest.fixture
def session(engine) -> Session:
    """Yield a SQLAlchemy session that is closed after the test."""
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    sess = factory()
    yield sess
    sess.close()


@pytest.fixture
def seeded(session: Session) -> Session:
    """Load Northstar demo customers, tickets, and knowledge articles."""
    seed_from_fixtures(session, REPO_DATA)
    session.commit()
    return session


@pytest.fixture
def app(settings: Settings, engine):
    """FastAPI app wired to FakeLLM so HTTP tests never call OpenAI."""
    return create_app(settings=settings, engine=engine, llm=FakeLLM())


@pytest.fixture
def client(app) -> TestClient:
    """In-process Starlette client for hitting dashboard routes."""
    return TestClient(app)
