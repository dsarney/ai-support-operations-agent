"""Knowledge-base FTS5 search tests against seeded articles."""

from src.knowledge.search import search_knowledge


def test_lockout_article_is_found(seeded):
    hits = search_knowledge(seeded, "account locked password retries")
    ids = [hit.article_id for hit in hits]
    assert "kb-account-lockout" in ids


def test_gateway_article_is_found(seeded):
    hits = search_knowledge(seeded, "API gateway 502 503 errors")
    ids = [hit.article_id for hit in hits]
    assert "kb-api-gateway-errors" in ids
