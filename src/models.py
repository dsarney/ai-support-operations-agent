"""SQLAlchemy models for the Northstar Cloud support-ops demo database."""

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db import Base, utcnow


class Customer(Base):
    """Workspace owner; tickets, invoices, and account state hang off this row."""

    __tablename__ = "customers"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    email: Mapped[str] = mapped_column(String(200))
    company: Mapped[str] = mapped_column(String(200))
    plan: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )

    subscription: Mapped[Optional["Subscription"]] = relationship(
        back_populates="customer"
    )
    account_state: Mapped[Optional["AccountState"]] = relationship(
        back_populates="customer"
    )
    tickets: Mapped[list["Ticket"]] = relationship(back_populates="customer")
    invoices: Mapped[list["Invoice"]] = relationship(back_populates="customer")


class Subscription(Base):
    """Billing plan attached to a customer (read-only for the agent)."""

    __tablename__ = "subscriptions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.id"))
    status: Mapped[str] = mapped_column(String(32))
    plan: Mapped[str] = mapped_column(String(32))
    seats: Mapped[int] = mapped_column(Integer, default=1)
    renews_on: Mapped[str] = mapped_column(String(32))

    customer: Mapped[Customer] = relationship(back_populates="subscription")


class AccountState(Base):
    """Mutable identity/integration flags the mock tools read and write."""

    __tablename__ = "account_states"

    customer_id: Mapped[str] = mapped_column(
        ForeignKey("customers.id"), primary_key=True
    )
    locked: Mapped[bool] = mapped_column(Boolean, default=False)
    lock_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    failed_sign_in_attempts: Mapped[int] = mapped_column(Integer, default=0)
    email_verified: Mapped[bool] = mapped_column(Boolean, default=True)
    verification_email_resent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    api_key_prefix: Mapped[str] = mapped_column(String(32), default="nsk_live_****")
    api_key_rotated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    webhook_url: Mapped[str | None] = mapped_column(String(255), nullable=True)
    webhook_status: Mapped[str] = mapped_column(String(32), default="healthy")
    webhook_last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    cache_stale: Mapped[bool] = mapped_column(Boolean, default=False)

    customer: Mapped[Customer] = relationship(back_populates="account_state")


class Invoice(Base):
    """Historical invoice used for billing-dispute investigation (never mutated)."""

    __tablename__ = "invoices"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.id"))
    amount_cents: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32))
    period: Mapped[str] = mapped_column(String(32))

    customer: Mapped[Customer] = relationship(back_populates="invoices")


class ServiceComponent(Base):
    """Platform health row (e.g. api-gateway degraded) used for incident correlation."""

    __tablename__ = "service_components"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(32))
    message: Mapped[str] = mapped_column(Text, default="")


class KnowledgeArticle(Base):
    """Internal help article; FTS5 index is maintained separately in knowledge_fts."""

    __tablename__ = "knowledge_articles"

    pk: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    id: Mapped[str] = mapped_column(String(64), unique=True)
    title: Mapped[str] = mapped_column(String(255))
    category: Mapped[str] = mapped_column(String(64))
    component: Mapped[str | None] = mapped_column(String(64), nullable=True)
    body: Mapped[str] = mapped_column(Text)
    path: Mapped[str] = mapped_column(String(255))


class Incident(Base):
    """Cluster of related tickets sharing a degraded component or knowledge articles."""

    __tablename__ = "incidents"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    title: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(32), default="open")
    component_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    summary: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )

    tickets: Mapped[list["IncidentTicket"]] = relationship(back_populates="incident")


class IncidentTicket(Base):
    """Many-to-many link between an incident and a ticket."""

    __tablename__ = "incident_tickets"

    incident_id: Mapped[str] = mapped_column(
        ForeignKey("incidents.id"), primary_key=True
    )
    ticket_id: Mapped[str] = mapped_column(ForeignKey("tickets.id"), primary_key=True)

    incident: Mapped[Incident] = relationship(back_populates="tickets")
    ticket: Mapped["Ticket"] = relationship(back_populates="incident_links")


class Ticket(Base):
    """Customer support ticket the agent classifies, investigates, and optionally remediates."""

    __tablename__ = "tickets"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.id"))
    subject: Mapped[str] = mapped_column(String(255))
    body: Mapped[str] = mapped_column(Text)
    channel: Mapped[str] = mapped_column(String(32), default="email")
    status: Mapped[str] = mapped_column(String(32), default="open")
    category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    priority: Mapped[str | None] = mapped_column(String(32), nullable=True)
    urgency: Mapped[str | None] = mapped_column(String(32), nullable=True)
    sentiment: Mapped[str | None] = mapped_column(String(32), nullable=True)
    pii_likely: Mapped[bool] = mapped_column(Boolean, default=False)
    classification_confidence: Mapped[float | None] = mapped_column(
        Float, nullable=True
    )
    kb_article_ids_json: Mapped[str] = mapped_column(
        Text, default="[]"
    )  # retrieved article ids
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )

    customer: Mapped[Customer] = relationship(back_populates="tickets")
    messages: Mapped[list["TicketMessage"]] = relationship(
        back_populates="ticket", order_by="TicketMessage.created_at"
    )
    runs: Mapped[list["AgentRun"]] = relationship(
        back_populates="ticket", order_by="AgentRun.started_at"
    )
    incident_links: Mapped[list[IncidentTicket]] = relationship(back_populates="ticket")


class TicketMessage(Base):
    """Customer or agent message on a ticket thread."""

    __tablename__ = "ticket_messages"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    ticket_id: Mapped[str] = mapped_column(ForeignKey("tickets.id"))
    author: Mapped[str] = mapped_column(String(32))
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )

    ticket: Mapped[Ticket] = relationship(back_populates="messages")


class AgentRun(Base):
    """One pipeline execution against a ticket, including JSON snapshots and outcome."""

    __tablename__ = "agent_runs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    ticket_id: Mapped[str] = mapped_column(ForeignKey("tickets.id"))
    status: Mapped[str] = mapped_column(String(32), default="running")
    outcome: Mapped[str | None] = mapped_column(String(64), nullable=True)
    model: Mapped[str] = mapped_column(String(64), default="")
    classification_json: Mapped[str] = mapped_column(Text, default="{}")
    diagnosis_json: Mapped[str] = mapped_column(Text, default="{}")
    policy_json: Mapped[str] = mapped_column(Text, default="{}")
    reply_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    ticket: Mapped[Ticket] = relationship(back_populates="runs")
    steps: Mapped[list["AgentStep"]] = relationship(
        back_populates="run", order_by="AgentStep.seq"
    )
    remediations: Mapped[list["RemediationAction"]] = relationship(back_populates="run")


class AgentStep(Base):
    """Ordered stage within a run (classify, investigate, policy, remediate, …)."""

    __tablename__ = "agent_steps"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("agent_runs.id"))
    seq: Mapped[int] = mapped_column(Integer)
    stage: Mapped[str] = mapped_column(String(32))
    summary: Mapped[str] = mapped_column(Text, default="")
    tool_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    tool_args_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    tool_result_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    output_json: Mapped[str] = mapped_column(Text, default="{}")
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    tokens: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )

    run: Mapped[AgentRun] = relationship(back_populates="steps")


class RemediationAction(Base):
    """Record of a mutating tool call and whether post-checks verified it."""

    __tablename__ = "remediation_actions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("agent_runs.id"))
    ticket_id: Mapped[str] = mapped_column(ForeignKey("tickets.id"))
    action_type: Mapped[str] = mapped_column(String(64))
    risk: Mapped[str] = mapped_column(String(32), default="low")
    result_json: Mapped[str] = mapped_column(Text, default="{}")
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )

    run: Mapped[AgentRun] = relationship(back_populates="remediations")


class AuditEvent(Base):
    """Append-only event log for policy decisions, tool calls, and human overrides."""

    __tablename__ = "audit_events"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ticket_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    event_type: Mapped[str] = mapped_column(String(64))
    actor: Mapped[str] = mapped_column(String(32), default="agent")
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
