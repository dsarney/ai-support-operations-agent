"""LLM client protocol plus the context objects passed into investigation and reply steps."""

from __future__ import annotations

from typing import Protocol

from src.schemas import (
    Classification,
    Diagnosis,
    InvestigationDecision,
    KnowledgeHit,
)


class InvestigationContext:
    """Inputs for choosing the next read-only tool (or stopping)."""

    def __init__(
        self,
        *,
        customer_id: str,
        subject: str,
        body: str,
        classification: Classification,
        kb_hits: list[KnowledgeHit],
        prior_steps: list[dict],
        available_tools: list[str],
    ) -> None:
        self.customer_id = customer_id
        self.subject = subject
        self.body = body
        self.classification = classification
        self.kb_hits = kb_hits
        self.prior_steps = prior_steps
        self.available_tools = available_tools


class ReplyContext:
    """Inputs for drafting the customer-facing message after policy and optional remediation."""

    def __init__(
        self,
        *,
        customer_name: str,
        subject: str,
        body: str,
        classification: Classification,
        diagnosis: Diagnosis,
        policy_reasons: list[str],
        kb_hits: list[KnowledgeHit],
        remediated: bool,
        verified: bool,
        escalate: bool,
        action: str | None,
    ) -> None:
        self.customer_name = customer_name
        self.subject = subject
        self.body = body
        self.classification = classification
        self.diagnosis = diagnosis
        self.policy_reasons = policy_reasons
        self.kb_hits = kb_hits
        self.remediated = remediated
        self.verified = verified
        self.escalate = escalate
        self.action = action


class LLMClient(Protocol):
    """Both OpenAIClient and FakeLLM implement this so the pipeline can swap them."""

    model_name: str

    def classify(self, subject: str, body: str) -> Classification: ...

    def next_investigation_action(
        self, context: InvestigationContext
    ) -> InvestigationDecision: ...

    def diagnose(
        self,
        subject: str,
        body: str,
        classification: Classification,
        kb_hits: list[KnowledgeHit],
        evidence: list[dict],
    ) -> Diagnosis: ...

    def draft_reply(self, context: ReplyContext) -> str: ...
