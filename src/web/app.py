"""FastAPI application factory for the SupportOps dashboard."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from sqlalchemy.engine import Engine
from starlette.templating import Jinja2Templates

from src.config import Settings, get_settings
from src.db import create_db_engine, create_schema, session_factory
from src.web.routes import router

PACKAGE_DIR = Path(__file__).resolve().parent


def _pretty_json(value) -> str:
    """Jinja filter: pretty-print JSON stored as a string on AgentRun rows."""
    if value is None:
        return "{}"
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return value
    return json.dumps(value, indent=2, default=str)


def _fmt_dt(value) -> str:
    """Jinja filter: render datetimes as UTC, or an em dash when missing."""
    if value is None:
        return "—"
    if hasattr(value, "strftime"):
        return value.strftime("%Y-%m-%d %H:%M UTC")
    return str(value)


def create_app(
    settings: Settings | None = None,
    engine: Engine | None = None,
    llm=None,
) -> FastAPI:
    """Build the app. Tests pass in a FakeLLM and a tmp SQLite engine."""
    settings = settings or get_settings()
    if engine is None:
        engine = create_db_engine(settings.database_url)
        create_schema(engine)

    app = FastAPI(
        title="SupportOps",
        description="AI support operations agent for the Northstar Cloud demo.",
        version="0.1.0",
    )
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = session_factory(engine)
    app.state.llm = llm  # None means routes construct OpenAIClient on demand

    templates = Jinja2Templates(directory=str(PACKAGE_DIR / "templates"))
    templates.env.filters["pretty_json"] = _pretty_json
    templates.env.filters["fmt_dt"] = _fmt_dt
    app.state.templates = templates

    static_dir = PACKAGE_DIR / "static"
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
    app.include_router(router)
    return app
