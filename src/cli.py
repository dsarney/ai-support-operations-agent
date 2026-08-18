"""Command-line entry points: seed, run-all, serve, and the combined demo."""

from __future__ import annotations

import argparse
import os
import threading
from pathlib import Path

import uvicorn
from sqlalchemy.orm import Session

from src.agent.pipeline import AgentPipeline
from src.config import Settings, get_settings
from src.db import create_db_engine, create_schema
from src.llm.fake import FakeLLM
from src.llm.openai_client import OpenAIClient
from src.models import Ticket
from src.seed import reset_and_seed
from src.web.app import create_app


def _ensure_sqlite_dir(database_url: str) -> None:
    """Create the parent directory for a sqlite:/// URL so the first connect succeeds."""
    prefix = "sqlite:///"
    if not database_url.startswith(prefix):
        return
    raw = database_url[len(prefix) :]
    # Absolute sqlite:////path vs relative sqlite:///./data/file.db
    if raw.startswith("/") and not raw.startswith("//"):
        path = Path(raw)
    else:
        path = Path(raw.lstrip("./"))
    if path.parent.as_posix() not in {"", "."}:
        path.parent.mkdir(parents=True, exist_ok=True)


def _build_llm(settings: Settings, fake: bool):
    """Use FakeLLM for CI/demo without an API key; otherwise the live OpenAI client."""
    if fake:
        return FakeLLM()
    return OpenAIClient(api_key=settings.openai_api_key, model=settings.openai_model)


def cmd_seed(settings: Settings) -> None:
    """Reset SQLite and load demo fixtures from DATA_DIR."""
    _ensure_sqlite_dir(settings.database_url)
    engine = create_db_engine(settings.database_url)
    data_dir = settings.resolved_data_dir()
    reset_and_seed(engine, data_dir)
    print(f"Seeded {settings.database_url} from {data_dir}", flush=True)


def cmd_run_all(settings: Settings, fake: bool) -> None:
    """Run the agent on every open or in-progress ticket."""
    engine = create_db_engine(settings.database_url)
    create_schema(engine)
    llm = _build_llm(settings, fake=fake)
    with Session(engine) as session:
        tickets = (
            session.query(Ticket)
            .filter(Ticket.status.in_(["open", "in_progress"]))
            .all()
        )
        if not tickets:
            print("No open tickets.")
            return
        for ticket in tickets:
            print(f"Running {ticket.id} — {ticket.subject}", flush=True)
            run = AgentPipeline(session, settings, llm).run(ticket.id)
            session.commit()
            print(f"  → {run.outcome or run.status}", flush=True)


def cmd_serve(settings: Settings, fake: bool, reload: bool) -> None:
    """Start the FastAPI dashboard (uvicorn)."""
    _ensure_sqlite_dir(settings.database_url)
    engine = create_db_engine(settings.database_url)
    create_schema(engine)
    # None means the dashboard will construct OpenAIClient on first agent run.
    llm = _build_llm(settings, fake=fake) if fake else None
    app = create_app(settings=settings, engine=engine, llm=llm)
    uvicorn.run(
        app,
        host=settings.host,
        port=settings.port,
        reload=reload,
    )


def cmd_demo(settings: Settings, fake: bool, no_run: bool) -> None:
    """Seed, start the dashboard immediately, then run tickets in the background."""
    cmd_seed(settings)
    print(f"\nDashboard: http://{settings.host}:{settings.port}", flush=True)
    print("Open that URL now. Tickets will fill in as the agent works.\n", flush=True)
    if not no_run:
        threading.Thread(
            target=cmd_run_all,
            args=(settings, fake),
            daemon=True,
            name="demo-run-all",
        ).start()
    cmd_serve(settings, fake=fake, reload=False)


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="src",
        description="Northstar Cloud AI support operations demo.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("seed", help="Reset the SQLite database and load demo fixtures")
    run_all = sub.add_parser("run-all", help="Run the agent on every open ticket")
    run_all.add_argument(
        "--fake-llm", action="store_true", help="Use the deterministic FakeLLM"
    )
    serve = sub.add_parser("serve", help="Start the FastAPI dashboard")
    serve.add_argument("--fake-llm", action="store_true")
    serve.add_argument("--reload", action="store_true")
    demo = sub.add_parser(
        "demo", help="Seed, start the dashboard, and run tickets in the background"
    )
    demo.add_argument("--fake-llm", action="store_true")
    demo.add_argument(
        "--no-run", action="store_true", help="Seed and serve without running the agent"
    )
    args = parser.parse_args()

    os.environ.setdefault("DATA_DIR", str(Path.cwd() / "data"))
    get_settings.cache_clear()  # pick up .env and the data-dir default above
    settings = get_settings()

    if args.command == "seed":
        cmd_seed(settings)
    elif args.command == "run-all":
        cmd_run_all(settings, fake=args.fake_llm)
    elif args.command == "serve":
        cmd_serve(settings, fake=args.fake_llm, reload=args.reload)
    elif args.command == "demo":
        cmd_demo(settings, fake=args.fake_llm, no_run=args.no_run)


if __name__ == "__main__":
    main()
