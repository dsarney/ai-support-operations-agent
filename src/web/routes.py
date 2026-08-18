"""HTML dashboard routes: tickets, knowledge, incidents, and manual agent runs."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session, selectinload

from src.agent.pipeline import AgentPipeline
from src.config import Settings
from src.db import utcnow
from src.models import (
    AgentRun,
    AuditEvent,
    Customer,
    Incident,
    IncidentTicket,
    KnowledgeArticle,
    ServiceComponent,
    Ticket,
    TicketMessage,
)
from src.util import new_id
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
    return {"ok": True}


@router.get("/", response_class=HTMLResponse)
def dashboard(request: Request, session: Session = Depends(get_session)):
    open_count = session.query(Ticket).filter(Ticket.status == "open").count()
    resolved = session.query(Ticket).filter(Ticket.status == "resolved").count()
    escalated = session.query(Ticket).filter(Ticket.status == "escalated").count()
    in_progress = session.query(Ticket).filter(Ticket.status == "in_progress").count()
    incidents = (
        session.query(Incident)
        .filter(Incident.status == "open")
        .order_by(Incident.updated_at.desc())
        .all()
    )
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
    components = session.query(ServiceComponent).order_by(ServiceComponent.name).all()
    return templates(request).TemplateResponse(
        request,
        "dashboard.html",
        {
            "stats": {
                "open": open_count,
                "in_progress": in_progress,
                "resolved": resolved,
                "escalated": escalated,
                "incidents": len(incidents),
                "auto_rate": rate,
            },
            "incidents": incidents,
            "recent": recent,
            "components": components,
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
    session.flush()
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
            selectinload(Ticket.incident_links).selectinload(IncidentTicket.incident),
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
    kb_ids = []
    try:
        kb_ids = json.loads(ticket.kb_article_ids_json or "[]")
    except json.JSONDecodeError:
        kb_ids = []
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
            "classification": _load_json(run.classification_json if run else None),
            "diagnosis": _load_json(run.diagnosis_json if run else None),
            "policy": _load_json(run.policy_json if run else None),
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


@router.get("/incidents", response_class=HTMLResponse)
def incidents_list(request: Request, session: Session = Depends(get_session)):
    incidents = (
        session.query(Incident)
        .options(selectinload(Incident.tickets).selectinload(IncidentTicket.ticket))
        .order_by(Incident.updated_at.desc())
        .all()
    )
    components = session.query(ServiceComponent).all()
    return templates(request).TemplateResponse(
        request,
        "incidents.html",
        {"incidents": incidents, "components": components},
    )


@router.get("/incidents/{incident_id}", response_class=HTMLResponse)
def incident_detail(
    request: Request, incident_id: str, session: Session = Depends(get_session)
):
    incident = (
        session.query(Incident)
        .options(
            selectinload(Incident.tickets)
            .selectinload(IncidentTicket.ticket)
            .selectinload(Ticket.customer)
        )
        .filter(Incident.id == incident_id)
        .one_or_none()
    )
    if incident is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    component = None
    if incident.component_id:
        component = session.get(ServiceComponent, incident.component_id)
    return templates(request).TemplateResponse(
        request,
        "incident_detail.html",
        {"incident": incident, "component": component},
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


def _load_json(raw: str | None) -> dict:
    """Parse JSON blobs stored on AgentRun; invalid payloads become an empty dict."""
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}
