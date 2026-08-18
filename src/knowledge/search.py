"""SQLite FTS5 knowledge search with a substring fallback when FTS returns nothing."""

from __future__ import annotations

import re

from sqlalchemy.orm import Session

from src.models import KnowledgeArticle
from src.schemas import KnowledgeHit

_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")


def sanitize_fts_query(query: str) -> str:
    """Turn free text into a safe FTS5 OR-query; never pass raw user text to MATCH."""
    tokens = _TOKEN_RE.findall(query)
    if not tokens:
        return "northstar"  # empty MATCH is invalid; fall back to a corpus-wide token
    return " OR ".join(tokens[:12])


def search_knowledge(
    session: Session, query: str, limit: int = 5
) -> list[KnowledgeHit]:
    match = sanitize_fts_query(query)
    rows = (
        session.connection()
        .exec_driver_sql(
            """
        SELECT article_id,
               highlight(knowledge_fts, 1, '', '') as title,
               snippet(knowledge_fts, 2, '', '', '...', 18) as snippet
        FROM knowledge_fts
        WHERE knowledge_fts MATCH ?
        ORDER BY rank
        LIMIT ?
        """,
            (match, limit),
        )
        .all()
    )
    hits: list[KnowledgeHit] = []
    for article_id, title, snippet in rows:
        article = session.query(KnowledgeArticle).filter_by(id=article_id).one_or_none()
        hits.append(
            KnowledgeHit(
                article_id=article_id,
                title=(article.title if article else title) or article_id,
                snippet=snippet or "",
                category=article.category if article else "",
                component=article.component if article else None,
            )
        )
    if hits:
        return hits
    # Fallback substring search when FTS has no match.
    like = f"%{query.strip()[:40]}%"
    articles = (
        session.query(KnowledgeArticle)
        .filter(
            (KnowledgeArticle.title.ilike(like)) | (KnowledgeArticle.body.ilike(like))
        )
        .limit(limit)
        .all()
    )
    return [
        KnowledgeHit(
            article_id=article.id,
            title=article.title,
            snippet=article.body[:180],
            category=article.category,
            component=article.component,
        )
        for article in articles
    ]
