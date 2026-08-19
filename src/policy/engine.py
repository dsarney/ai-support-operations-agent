"""Deterministic allow / deny / escalate gate. The LLM cannot override these rules."""

from __future__ import annotations

import re

from src.models import Customer, Ticket
from src.schemas import Classification, Diagnosis, PolicyDecision

# Categories that always go to a human, regardless of model confidence.
ESCALATE_CATEGORIES = {
    "legal",
    "security_abuse",
    "data_deletion",
    "billing_dispute",
    "refund",
}

# The only mutations the agent may execute automatically.
ALLOWLISTED_ACTIONS = {
    "unlock_account",
    "resend_verification_email",
    "rotate_workspace_api_key",
    "retry_failed_webhook",
    "clear_workspace_cache",
    "none",
}

# Safe even for enterprise-critical tickets; everything else needs a human.
TRIVIAL_ACTIONS = {
    "unlock_account",
    "resend_verification_email",
    "none",
}

# Never automated, even if the model recommends them.
DENIED_ACTIONS = {
    "issue_refund",
    "grant_credits",
    "change_plan",
    "delete_account",
    "export_data",
    "impersonate_admin",
}

LEGAL_THREAT_RE = re.compile(
    r"\b(sue|lawsuit|attorney|solicitor|gdpr|ccpa|legal action|"
    r"right to be forgotten|delete all (my|our) data)\b",
    re.IGNORECASE,
)
TAKEOVER_RE = re.compile(
    r"(didn'?t (log|sign) in|unrecognized (login|device|location)|"
    r"account (was )?hacked|i think we were hacked|\bstolen\b)",
    re.IGNORECASE,
)


# Pure Python: unit-tested independently of any LLM.
def evaluate_policy(
    *,
    classification: Classification,
    diagnosis: Diagnosis,
    ticket: Ticket,
    customer: Customer,
    auto_remediate: bool,
    classify_threshold: float,
    diagnose_threshold: float,
    mutating_already_done: bool = False,
) -> PolicyDecision:
    """Decide whether to auto-remediate, reply-only resolve, or escalate to a human."""
    reasons: list[str] = []
    escalate = False
    risk: str = "low"
    action = diagnosis.recommended_action or "none"

    if classification.confidence < classify_threshold:
        escalate = True
        risk = "medium"
        reasons.append("classification confidence below threshold")

    if diagnosis.confidence < diagnose_threshold:
        escalate = True
        risk = "medium"
        reasons.append("diagnosis confidence below threshold")

    if classification.category in ESCALATE_CATEGORIES:
        escalate = True
        risk = "high"
        reasons.append(f"category '{classification.category}' requires human review")

    if action in DENIED_ACTIONS:
        escalate = True
        risk = "high"
        reasons.append(f"action '{action}' is never automated")

    if action not in ALLOWLISTED_ACTIONS:
        escalate = True
        risk = "high"
        reasons.append(f"action '{action}' is not on the mutating allowlist")

    if mutating_already_done and action not in {"none"}:
        escalate = True
        reasons.append("a mutating action was already attempted in this run")

    if (
        customer.plan == "enterprise"
        and classification.priority == "critical"
        and action not in TRIVIAL_ACTIONS
    ):
        escalate = True
        risk = "high"
        reasons.append(
            "enterprise critical tickets need a human for non-trivial actions"
        )

    text = f"{ticket.subject}\n{ticket.body}"
    if LEGAL_THREAT_RE.search(text):
        escalate = True
        risk = "high"
        reasons.append("ticket text appears to contain a legal or regulatory request")

    if TAKEOVER_RE.search(text):
        escalate = True
        risk = "high"
        reasons.append("suspected account takeover")

    # A service_component hint (e.g. api-gateway on a how-to ticket) is not
    # enough to escalate; only an explicit outage category requires a human.
    if classification.category == "outage":
        escalate = True
        risk = "high"
        reasons.append("outage tickets require human-owned incident response")

    if diagnosis.requires_human:
        escalate = True
        reasons.append("model flagged the case as requiring a human")

    allow = (
        auto_remediate
        and not escalate
        and action in ALLOWLISTED_ACTIONS
        and action != "none"
    )
    resolve_with_reply = (not escalate) and action == "none"

    if not reasons:
        if allow:
            reasons.append(f"allowlisted low-risk action '{action}'")
        elif resolve_with_reply:
            reasons.append(
                "no mutation required; resolve with a knowledge-backed reply"
            )

    return PolicyDecision(
        allow_auto_remediation=allow,
        allowed_action=action if allow else None,
        escalate=escalate,
        reasons=reasons,
        risk=risk,  # type: ignore[arg-type]
        resolve_with_reply=resolve_with_reply,
    )
