"""LLM client protocol plus the context objects passed into investigation and reply steps."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from src.schemas import (
    Classification,
    Diagnosis,
    InvestigationDecision,
    KnowledgeHit,
)


@dataclass(kw_only=True)
class InvestigationContext:
    """Inputs for choosing the next read-only tool (or stopping)."""

    customer_id: str
    subject: str
    body: str
    classification: Classification
    kb_hits: list[KnowledgeHit]
    prior_steps: list[dict]
    available_tools: list[str]


@dataclass(kw_only=True)
class ReplyContext:
    """Inputs for drafting the customer-facing message after policy and optional remediation."""

    customer_name: str
    subject: str
    body: str
    classification: Classification
    diagnosis: Diagnosis
    policy_reasons: list[str]
    kb_hits: list[KnowledgeHit]
    remediated: bool
    verified: bool
    escalate: bool
    action: str | None


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
