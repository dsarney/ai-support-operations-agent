"""Load demo customers, tickets, and markdown knowledge articles into SQLite."""

from __future__ import annotations

import json
import re
from pathlib import Path

from sqlalchemy.orm import Session

from src.db import create_schema, drop_schema
from src.models import (
    AccountState,
    Customer,
    Invoice,
    KnowledgeArticle,
    ServiceComponent,
    Subscription,
    Ticket,
    TicketMessage,
)
from src.util import new_id

FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n(.*)$", re.DOTALL)


def _parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """Split YAML-like `---` front matter from the markdown body."""
    match = FRONTMATTER_RE.match(text)
    if not match:
        return {}, text.strip()
    meta: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        meta[key.strip()] = value.strip()
    return meta, match.group(2).strip()


def load_knowledge(session: Session, knowledge_dir: Path) -> int:
    """Insert articles and rebuild the FTS5 index used by search."""
    count = 0
    session.connection().exec_driver_sql("DELETE FROM knowledge_fts")
    for path in sorted(knowledge_dir.glob("*.md")):
        meta, body = _parse_frontmatter(path.read_text(encoding="utf-8"))
        article = KnowledgeArticle(
            id=meta.get("id", path.stem),
            title=meta.get("title", path.stem),
            category=meta.get("category", "other"),
            component=meta.get("component") or None,
            body=body,
            path=(
                str(path.relative_to(knowledge_dir.parent.parent))
                if knowledge_dir.parent.parent in path.parents
                else str(path)
            ),
        )
        session.add(article)
        session.flush()
        session.connection().exec_driver_sql(
            "INSERT INTO knowledge_fts(article_id, title, body) VALUES (?, ?, ?)",
            (article.id, article.title, article.body),
        )
        count += 1
    return count


def seed_from_fixtures(session: Session, data_dir: Path) -> None:
    """Populate an existing schema from data/fixtures/demo.json plus knowledge/*.md."""
    payload = json.loads(
        (data_dir / "fixtures" / "demo.json").read_text(encoding="utf-8")
    )

    for row in payload["customers"]:
        session.add(Customer(**row))
    for row in payload["subscriptions"]:
        session.add(Subscription(**row))
    for row in payload["account_states"]:
        session.add(AccountState(**row))
    for row in payload["invoices"]:
        session.add(Invoice(**row))
    for row in payload["service_components"]:
        session.add(ServiceComponent(**row))
    for row in payload["tickets"]:
        ticket = Ticket(status="open", **row)
        session.add(ticket)
        session.add(
            TicketMessage(
                id=new_id("msg"),
                ticket_id=ticket.id,
                author="customer",
                body=ticket.body,
            )
        )

    load_knowledge(session, data_dir / "knowledge")
    session.flush()


def reset_and_seed(engine, data_dir: Path) -> None:
    """Drop and recreate all tables, then load demo fixtures (used by `python -m src seed`)."""
    drop_schema(engine)
    create_schema(engine)
    with Session(engine) as session:
        seed_from_fixtures(session, data_dir)
        session.commit()
