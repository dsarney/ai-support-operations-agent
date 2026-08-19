"""Group related tickets into incidents when a component is degraded or articles overlap."""

from __future__ import annotations

from sqlalchemy.orm import Session

from src.db import utcnow
from src.models import Incident, IncidentTicket, ServiceComponent, Ticket
from src.schemas import Diagnosis
from src.util import loads_list, new_id

OPEN_STATUSES = {
    "open",
    "in_progress",
    "escalated",
}  # resolved tickets do not join a cluster


def correlate_ticket(
    session: Session, ticket: Ticket, diagnosis: Diagnosis
) -> Incident | None:
    """Attach the ticket to an existing open incident, or open a new one when the pattern matches."""
    component_id = diagnosis.service_component
    component = None
    if component_id:
        component = session.get(ServiceComponent, component_id)

    if component is not None and component.status != "operational":
        # Platform health is the strongest signal: all tickets on a degraded component share one incident.
        return _attach_or_create(
            session,
            ticket,
            title=f"{component.name} {component.status}",
            component_id=component.id,
            category=ticket.category,
            summary=component.message,
        )

    if ticket.category == "outage":
        return _attach_or_create(
            session,
            ticket,
            title="Possible platform outage",
            component_id=component_id,
            category="outage",
            summary=diagnosis.likely_cause,
        )

    article_ids = set(_article_ids(ticket))
    if not article_ids or not ticket.category:
        return None

    similar: list[Ticket] = []
    candidates = (
        session.query(Ticket)
        .filter(Ticket.category == ticket.category, Ticket.status.in_(OPEN_STATUSES))
        .all()
    )
    for other in candidates:
        if other.id == ticket.id:
            continue
        if article_ids & set(_article_ids(other)):
            similar.append(other)

    cluster = [ticket, *similar]
    # Need at least three overlapping tickets before treating it as a cluster, not coincidence.
    if len(cluster) < 3:
        return None
    return _attach_or_create(
        session,
        ticket,
        title=f"Clustered {ticket.category} tickets",
        component_id=component_id,
        category=ticket.category,
        summary=f"{len(cluster)} open tickets share knowledge articles {sorted(article_ids)}",
        extra_tickets=similar,
    )


def _article_ids(ticket: Ticket) -> list[str]:
    return [str(item) for item in loads_list(ticket.kb_article_ids_json)]


def _attach_or_create(
    session: Session,
    ticket: Ticket,
    *,
    title: str,
    component_id: str | None,
    category: str | None,
    summary: str,
    extra_tickets: list[Ticket] | None = None,
) -> Incident:
    """Reuse the open incident for this component/category so related tickets collapse together."""
    query = session.query(Incident).filter(Incident.status == "open")
    if component_id:
        incident = query.filter(Incident.component_id == component_id).one_or_none()
    else:
        incident = query.filter(
            Incident.category == category, Incident.component_id.is_(None)
        ).one_or_none()

    if incident is None:
        incident = Incident(
            id=new_id("inc"),
            title=title,
            status="open",
            component_id=component_id,
            category=category,
            summary=summary,
        )
        session.add(incident)
        session.flush()

    for linked in [ticket, *(extra_tickets or [])]:
        exists = (
            session.query(IncidentTicket)
            .filter_by(incident_id=incident.id, ticket_id=linked.id)
            .one_or_none()
        )
        if exists is None:
            session.add(IncidentTicket(incident_id=incident.id, ticket_id=linked.id))

    incident.updated_at = utcnow()
    session.flush()
    return incident
