"""HTML dashboard routes: tickets, knowledge, and manual agent runs."""

from __future__ import annotations

import re

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session, selectinload

from src.agent.pipeline import AgentPipeline
from src.config import Settings
from src.db import retry_on_lock, utcnow
from src.models import (
    AgentRun,
    AuditEvent,
    Customer,
    KnowledgeArticle,
    Ticket,
    TicketMessage,
)
from src.util import loads_dict, loads_list, new_id
from src.web.deps import get_session, resolve_llm

router = APIRouter()


def templates(request: Request):
    """Jinja environment stored on the FastAPI app at startup."""
    return request.app.state.templates


def settings(request: Request) -> Settings:
    """Settings injected into routes that start the agent pipeline."""
    return request.app.state.settings


@router.get("/healthz")
def healthz() -> dict:
    """Liveness probe used by tests and process monitors."""
    return {"ok": True}


@router.get("/", response_class=HTMLResponse)
def dashboard(request: Request, session: Session = Depends(get_session)):
    open_count = session.query(Ticket).filter(Ticket.status == "open").count()
    resolved = session.query(Ticket).filter(Ticket.status == "resolved").count()
    escalated = session.query(Ticket).filter(Ticket.status == "escalated").count()
    in_progress = session.query(Ticket).filter(Ticket.status == "in_progress").count()
    completed_runs = (
        session.query(AgentRun).filter(AgentRun.status == "completed").count()
    )
    auto_resolved_runs = (
        session.query(AgentRun).filter(AgentRun.outcome == "resolved").count()
    )
    # Percentage of completed runs that auto-resolved (not escalated).
    rate = round(100 * auto_resolved_runs / completed_runs) if completed_runs else 0
    recent = (
        session.query(Ticket)
        .options(selectinload(Ticket.customer))
        .order_by(Ticket.updated_at.desc())
        .limit(8)
        .all()
    )
    return templates(request).TemplateResponse(
        request,
        "dashboard.html",
        {
            "stats": {
                "open": open_count,
                "in_progress": in_progress,
                "resolved": resolved,
                "escalated": escalated,
                "auto_rate": rate,
            },
            "recent": recent,
        },
    )


@router.get("/tickets", response_class=HTMLResponse)
def tickets_list(
    request: Request,
    session: Session = Depends(get_session),
    status: str = Query(default=""),
    priority: str = Query(default=""),
    q: str = Query(default=""),
):
    query = session.query(Ticket).options(selectinload(Ticket.customer))
    if status:
        query = query.filter(Ticket.status == status)
    if priority:
        query = query.filter(Ticket.priority == priority)
    if q:
        like = f"%{q}%"
        query = query.filter((Ticket.subject.ilike(like)) | (Ticket.id.ilike(like)))
    tickets = query.order_by(Ticket.created_at.desc()).all()
    return templates(request).TemplateResponse(
        request,
        "tickets.html",
        {"tickets": tickets, "status": status, "priority": priority, "q": q},
    )


@router.get("/tickets/new", response_class=HTMLResponse)
def new_ticket_form(request: Request, session: Session = Depends(get_session)):
    customers = session.query(Customer).order_by(Customer.company).all()
    return templates(request).TemplateResponse(
        request,
        "new_ticket.html",
        {"customers": customers},
    )


@router.post("/tickets/new")
def create_ticket(
    request: Request,
    session: Session = Depends(get_session),
    cfg: Settings = Depends(settings),
    customer_id: str = Form(),
    subject: str = Form(),
    body: str = Form(),
    channel: str = Form(default="email"),
    run_now: str = Form(default=""),
):
    customer = session.get(Customer, customer_id)
    if customer is None:
        raise HTTPException(status_code=400, detail="Unknown customer")
    ticket_id = _next_ticket_id(session)
    ticket = Ticket(
        id=ticket_id,
        customer_id=customer_id,
        subject=subject.strip(),
        body=body.strip(),
        channel=channel,
        status="open",
    )
    session.add(ticket)
    session.add(
        TicketMessage(
            id=new_id("msg"), ticket_id=ticket_id, author="customer", body=body.strip()
        )
    )
    if run_now:
        llm = resolve_llm(request.app)
        AgentPipeline(session, cfg, llm).run(ticket_id)
    # 303 so a browser refresh does not re-POST the ticket form.
    return RedirectResponse(f"/tickets/{ticket_id}", status_code=303)


@router.get("/tickets/{ticket_id}", response_class=HTMLResponse)
def ticket_detail(
    request: Request, ticket_id: str, session: Session = Depends(get_session)
):
    ticket = (
        session.query(Ticket)
        .options(
            selectinload(Ticket.customer),
            selectinload(Ticket.messages),
            selectinload(Ticket.runs).selectinload(AgentRun.steps),
            selectinload(Ticket.runs).selectinload(AgentRun.remediations),
        )
        .filter(Ticket.id == ticket_id)
        .one_or_none()
    )
    if ticket is None:
        raise HTTPException(status_code=404, detail="Ticket not found")
    run = ticket.runs[-1] if ticket.runs else None  # latest agent attempt, if any
    audit = (
        session.query(AuditEvent)
        .filter(AuditEvent.ticket_id == ticket_id)
        .order_by(AuditEvent.created_at.desc())
        .limit(40)
        .all()
    )
    kb_ids = loads_list(ticket.kb_article_ids_json)
    articles = []
    if kb_ids:
        articles = (
            session.query(KnowledgeArticle)
            .filter(KnowledgeArticle.id.in_(kb_ids))
            .all()
        )
    return templates(request).TemplateResponse(
        request,
        "ticket_detail.html",
        {
            "ticket": ticket,
            "run": run,
            "audit": audit,
            "articles": articles,
            "classification": loads_dict(run.classification_json if run else None),
            "diagnosis": loads_dict(run.diagnosis_json if run else None),
            "policy": loads_dict(run.policy_json if run else None),
        },
    )


@router.post("/tickets/{ticket_id}/run")
def run_ticket(
    request: Request,
    ticket_id: str,
    session: Session = Depends(get_session),
    cfg: Settings = Depends(settings),
):
    ticket = session.get(Ticket, ticket_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail="Ticket not found")
    llm = resolve_llm(request.app)
    AgentPipeline(session, cfg, llm).run(ticket_id)
    return RedirectResponse(f"/tickets/{ticket_id}", status_code=303)


@router.post("/tickets/{ticket_id}/escalate")
def escalate_ticket(ticket_id: str, session: Session = Depends(get_session)):
    ticket = session.get(Ticket, ticket_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail="Ticket not found")
    ticket.status = "escalated"
    ticket.updated_at = utcnow()
    session.add(
        AuditEvent(
            id=new_id("aud"),
            ticket_id=ticket.id,
            event_type="manual_escalate",
            actor="human",
            payload_json="{}",
        )
    )
    return RedirectResponse(f"/tickets/{ticket_id}", status_code=303)


@router.get("/knowledge", response_class=HTMLResponse)
def knowledge_list(
    request: Request,
    session: Session = Depends(get_session),
    q: str = Query(default=""),
):
    query = session.query(KnowledgeArticle)
    if q:
        like = f"%{q}%"
        query = query.filter(
            (KnowledgeArticle.title.ilike(like)) | (KnowledgeArticle.body.ilike(like))
        )
    articles = query.order_by(KnowledgeArticle.title).all()
    return templates(request).TemplateResponse(
        request,
        "knowledge.html",
        {"articles": articles, "q": q},
    )


@router.get("/knowledge/new", response_class=HTMLResponse)
def new_knowledge_form(request: Request):
    return templates(request).TemplateResponse(request, "knowledge_new.html", {})


@router.post("/knowledge/new")
def create_knowledge_article(
    request: Request,
    session: Session = Depends(get_session),
    article_id: str = Form(default=""),
    title: str = Form(),
    category: str = Form(),
    component: str = Form(default=""),
    body: str = Form(),
):
    title = title.strip()
    category = category.strip()
    component = component.strip() or None
    body = body.strip()
    if not title or not category or not body:
        raise HTTPException(status_code=400, detail="title, category, and body are required")

    article_id = _allocate_knowledge_id(session, article_id, title)

    existing = session.query(KnowledgeArticle).filter_by(id=article_id).one_or_none()
    path = f"ui://{article_id}"

    if existing is not None:
        existing.title = title
        existing.category = category
        existing.component = component
        existing.body = body
        existing.path = path
        article = existing
    else:
        article = KnowledgeArticle(
            id=article_id,
            title=title,
            category=category,
            component=component,
            body=body,
            path=path,
        )
        session.add(article)

    _sync_fts(session, article_id, article.title, article.body)

    # 303 so a browser refresh does not re-submit the form.
    return RedirectResponse(f"/knowledge/{article_id}", status_code=303)


@router.get("/knowledge/{article_id}", response_class=HTMLResponse)
def knowledge_detail(
    request: Request, article_id: str, session: Session = Depends(get_session)
):
    article = session.query(KnowledgeArticle).filter_by(id=article_id).one_or_none()
    if article is None:
        raise HTTPException(status_code=404, detail="Article not found")
    return templates(request).TemplateResponse(
        request, "knowledge_detail.html", {"article": article}
    )


def _next_ticket_id(session: Session) -> str:
    """Allocate the next TCK-NNNN id from existing tickets (demo-scale, not concurrent-safe)."""
    ids = [row[0] for row in session.query(Ticket.id).all()]
    nums = []
    for item in ids:
        if item.startswith("TCK-"):
            try:
                nums.append(int(item.split("-", 1)[1]))
            except ValueError:
                continue
    next_n = max(nums) + 1 if nums else 1001
    return f"TCK-{next_n:04d}"


def _sync_fts(session: Session, article_id: str, title: str, body: str) -> None:
    """Update the FTS5 index, retrying on transient SQLite locks."""

    def _write() -> None:
        conn = session.connection()
        conn.exec_driver_sql(
            "DELETE FROM knowledge_fts WHERE article_id = ?",
            (article_id,),
        )
        conn.exec_driver_sql(
            "INSERT INTO knowledge_fts(article_id, title, body) VALUES (?, ?, ?)",
            (article_id, title, body),
        )

    retry_on_lock(_write)


_KNOWLEDGE_SLUG_RE = re.compile(r"[^a-zA-Z0-9]+")


def _slugify(value: str) -> str:
    """Turn a title into a short URL-safe id stem (letters, digits, hyphens)."""
    slug = _KNOWLEDGE_SLUG_RE.sub("-", value.strip().lower()).strip("-")
    return (slug or "knowledge")[:48]


def _allocate_knowledge_id(session: Session, requested_id: str, title: str) -> str:
    requested_id = requested_id.strip()
    if requested_id:
        # If an article already exists with this id, we treat it as an update.
        return requested_id[:64]

    base = _slugify(title)
    candidate = base
    i = 2
    while session.query(KnowledgeArticle).filter_by(id=candidate).one_or_none() is not None:
        candidate = f"{base}-{i}"
        candidate = candidate[:64]
        i += 1
    return candidate
