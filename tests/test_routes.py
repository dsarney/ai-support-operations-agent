"""Dashboard HTTP tests using FakeLLM (no OpenAI calls)."""

from pathlib import Path

from src.seed import seed_from_fixtures

REPO_DATA = Path(__file__).resolve().parents[1] / "data"


def _seed(app) -> None:
    """Load demo fixtures into the test app's database."""
    session = app.state.session_factory()
    seed_from_fixtures(session, REPO_DATA)
    session.commit()
    session.close()


def test_healthz(client):
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_pages_render_after_seed(client, app):
    _seed(app)

    for path in (
        "/",
        "/tickets",
        "/knowledge",
        "/knowledge/new",
        "/tickets/new",
        "/tickets/TCK-1001",
    ):
        response = client.get(path)
        assert response.status_code == 200, path
        assert "Overview" in response.text
        if path in ("/tickets", "/tickets/new"):
            assert "New ticket" in response.text


def test_run_ticket_with_fake_llm(client, app):
    _seed(app)

    response = client.post("/tickets/TCK-1001/run", follow_redirects=True)
    assert response.status_code == 200
    assert "resolved" in response.text
    assert "unlock_account" in response.text or "verified" in response.text
    assert 'id="ticket-page"' in response.text


def test_ticket_filters_and_knowledge_search(client, app):
    _seed(app)

    tickets = client.get("/tickets?status=open")
    assert tickets.status_code == 200
    assert 'hx-get="/tickets"' in tickets.text
    assert 'id="tickets-page"' in tickets.text

    knowledge = client.get("/knowledge?q=lockout")
    assert knowledge.status_code == 200
    assert "Account lockout" in knowledge.text
    assert 'hx-get="/knowledge"' in knowledge.text


def test_create_knowledge_article(client, app):
    _seed(app)

    payload = {
        "article_id": "ui-lockout-playbook",
        "title": "UI Knowledge: Lockout Playbook",
        "category": "security",
        "component": "",
        "body": "If users hit account lockout, verify password retries and email verification.",
    }
    response = client.post("/knowledge/new", data=payload, follow_redirects=True)
    assert response.status_code == 200
    assert "UI Knowledge: Lockout Playbook" in response.text

    # Ensure the FTS index is updated (search uses `/knowledge?q=...`).
    search = client.get("/knowledge?q=lockout")
    assert search.status_code == 200
    assert "UI Knowledge: Lockout Playbook" in search.text


def test_escalate_ticket(client, app):
    _seed(app)

    response = client.post("/tickets/TCK-1001/escalate", follow_redirects=True)
    assert response.status_code == 200
    assert "escalated" in response.text
    assert 'hx-post="/tickets/TCK-1001/escalate"' not in response.text
