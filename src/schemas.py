"""Pydantic contracts exchanged between the LLM, policy engine, and tool registry."""

from typing import Any, Literal

from pydantic import BaseModel, Field

Category = Literal[
    "access",
    "billing",
    "integrations",
    "performance",
    "how_to",
    "legal",
    "security_abuse",
    "data_deletion",
    "billing_dispute",
    "refund",
    "outage",
    "other",
]

Priority = Literal["low", "medium", "high", "critical"]
Urgency = Literal["low", "medium", "high"]
Sentiment = Literal["positive", "neutral", "frustrated", "angry"]


class Classification(BaseModel):
    """Structured output of the classify stage."""

    category: Category
    priority: Priority
    urgency: Urgency
    sentiment: Sentiment
    pii_likely: bool = False
    confidence: float = Field(ge=0, le=1)
    summary: str


class Diagnosis(BaseModel):
    """Structured output of the diagnose stage, including a recommended mutation or none."""

    likely_cause: str
    evidence: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)
    recommended_action: str
    service_component: str | None = None
    requires_human: bool = False


class InvestigationDecision(BaseModel):
    """Next read-only tool to call, or done=True when enough evidence is collected."""

    done: bool = False
    tool_name: str | None = None
    args: dict[str, Any] = Field(default_factory=dict)
    summary: str = ""


class ToolResult(BaseModel):
    """Uniform return value from every mock Northstar tool."""

    ok: bool
    data: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None

    def to_payload(self) -> dict[str, Any]:
        return {"ok": self.ok, "data": self.data, "error": self.error}


class PolicyDecision(BaseModel):
    """Deterministic gate output: auto-remediate, reply-only resolve, or escalate."""

    allow_auto_remediation: bool
    allowed_action: str | None = None
    escalate: bool
    reasons: list[str] = Field(default_factory=list)
    risk: Literal["low", "medium", "high"] = "low"
    resolve_with_reply: bool = False


class KnowledgeHit(BaseModel):
    """One article returned from FTS5 (or substring fallback) search."""

    article_id: str
    title: str
    snippet: str
    category: str = ""
    component: str | None = None
