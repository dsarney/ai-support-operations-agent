"""FastAPI request helpers: per-request DB session and LLM resolution."""

from __future__ import annotations

from collections.abc import Generator

from fastapi import Request
from sqlalchemy.orm import Session

from src.config import Settings
from src.llm.openai_client import OpenAIClient


def get_session(request: Request) -> Generator[Session, None, None]:
    """Yield a session that commits on success and rolls back on error."""
    factory = request.app.state.session_factory
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def resolve_llm(app):
    """Prefer an LLM injected on app.state (tests); otherwise construct OpenAIClient."""
    if getattr(app.state, "llm", None) is not None:
        return app.state.llm
    settings: Settings = app.state.settings
    return OpenAIClient(api_key=settings.openai_api_key, model=settings.openai_model)
