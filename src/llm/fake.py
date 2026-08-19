"""Keyword-driven FakeLLM used by tests. Does not call OpenAI."""

from __future__ import annotations

from src.llm.base import InvestigationContext, ReplyContext
from src.schemas import (
    Classification,
    Diagnosis,
    InvestigationDecision,
    KnowledgeHit,
)


def _text(subject: str, body: str) -> str:
    """Lowercased subject+body so keyword matching is case-insensitive."""
    return f"{subject}\n{body}".lower()


class FakeLLM:
    """Deterministic stand-in used by tests and CI. Does not call OpenAI."""

    model_name = "fake-llm"

    def classify(self, subject: str, body: str) -> Classification:
        """Map ticket text to a category. First matching keyword wins."""
        # High-risk categories (refund, GDPR, takeover, dispute, outage) come first
        # so they are never shadowed by a later lockout or how-to match.
        text = _text(subject, body)
        if "refund" in text:
            return Classification(
                category="refund",
                priority="high",
                urgency="high",
                sentiment="angry",
                confidence=0.93,
                summary="Customer demands a refund.",
            )
        if "gdpr" in text or "delete all" in text:
            return Classification(
                category="data_deletion",
                priority="high",
                urgency="high",
                sentiment="neutral",
                pii_likely=True,
                confidence=0.95,
                summary="Legal data deletion request.",
            )
        if "hacked" in text or "didn't log in" in text or "did not log in" in text:
            return Classification(
                category="security_abuse",
                priority="critical",
                urgency="high",
                sentiment="frustrated",
                confidence=0.91,
                summary="Possible account takeover.",
            )
        if "charged twice" in text or "billing dispute" in text:
            return Classification(
                category="billing_dispute",
                priority="high",
                urgency="medium",
                sentiment="frustrated",
                confidence=0.9,
                summary="Billing dispute over charges.",
            )
        if "502" in text or "503" in text or "timeout" in text or "api gateway" in text:
            return Classification(
                category="outage",
                priority=(
                    "critical" if "critical" in text or "enterprise" in text else "high"
                ),
                urgency="high",
                sentiment="frustrated",
                confidence=0.86,
                summary="Possible API gateway incident.",
            )
        # Low-risk issues the policy may auto-remediate.
        if "locked" in text or "lockout" in text:
            return Classification(
                category="access",
                priority="high",
                urgency="high",
                sentiment="frustrated",
                confidence=0.92,
                summary="Account lockout after failed sign-in.",
            )
        if "verification email" in text:
            return Classification(
                category="access",
                priority="medium",
                urgency="medium",
                sentiment="neutral",
                confidence=0.9,
                summary="Missing verification email.",
            )
        if "webhook" in text:
            return Classification(
                category="integrations",
                priority="high",
                urgency="medium",
                sentiment="frustrated",
                confidence=0.88,
                summary="Outbound webhook delivery failure.",
            )
        if "cache" in text or "dashboard" in text and "yesterday" in text:
            return Classification(
                category="performance",
                priority="medium",
                urgency="low",
                sentiment="neutral",
                confidence=0.85,
                summary="Stale workspace dashboard.",
            )
        if "api key" in text:
            return Classification(
                category="access",
                priority="high",
                urgency="high",
                sentiment="neutral",
                confidence=0.87,
                summary="Request to rotate a workspace API key.",
            )
        # Documentation questions and vague tickets — no mutation.
        if "sso" in text or "okta" in text or "invite" in text or "rate limit" in text:
            return Classification(
                category="how_to",
                priority="low",
                urgency="low",
                sentiment="positive" if "thanks" in text else "neutral",
                confidence=0.9,
                summary="Documentation / how-to question.",
            )
        if "broken" in text or "nothing works" in text:
            return Classification(
                category="other",
                priority="medium",
                urgency="medium",
                sentiment="angry",
                confidence=0.34,
                summary="Vague report with little detail.",
            )
        return Classification(
            category="other",
            priority="low",
            urgency="low",
            sentiment="neutral",
            confidence=0.4,
            summary="Unclassified ticket.",
        )

    def next_investigation_action(
        self, context: InvestigationContext
    ) -> InvestigationDecision:
        """Pick the next read-only tool, or stop when enough evidence is collected."""
        called = {step.get("tool") for step in context.prior_steps}
        cid = context.customer_id
        # Always load customer + platform health first, then ticket-specific reads.
        if "get_customer" not in called:
            return InvestigationDecision(
                done=False,
                tool_name="get_customer",
                args={"customer_id": cid},
                summary="Load customer record",
            )
        if "get_service_status" not in called:
            return InvestigationDecision(
                done=False,
                tool_name="get_service_status",
                args={},
                summary="Check platform health",
            )
        text = _text(context.subject, context.body)
        if (
            "locked" in text or "lockout" in text
        ) and "get_login_lockout" not in called:
            return InvestigationDecision(
                done=False,
                tool_name="get_login_lockout",
                args={"customer_id": cid},
                summary="Check lockout state",
            )
        if "verification" in text and "get_login_lockout" not in called:
            return InvestigationDecision(
                done=False,
                tool_name="get_login_lockout",
                args={"customer_id": cid},
                summary="Check verification state",
            )
        needs_integrations = any(
            token in text
            for token in ("webhook", "api key", "cache", "dashboard", "charged")
        )
        if needs_integrations and "get_workspace_integrations" not in called:
            return InvestigationDecision(
                done=False,
                tool_name="get_workspace_integrations",
                args={"customer_id": cid},
                summary="Check workspace integrations",
            )
        if ("charged" in text or "invoice" in text or "refund" in text) and (
            "get_recent_invoices" not in called
        ):
            return InvestigationDecision(
                done=False,
                tool_name="get_recent_invoices",
                args={"customer_id": cid},
                summary="Load invoices",
            )
        return InvestigationDecision(done=True, summary="Enough evidence collected")

    def diagnose(
        self,
        subject: str,
        body: str,
        classification: Classification,
        kb_hits: list[KnowledgeHit],
        evidence: list[dict],
    ) -> Diagnosis:
        """Recommend an action from category plus ticket keywords. Order matches classify()."""
        text = _text(subject, body)
        # Escalate-only categories: never recommend a mutating action.
        if classification.category == "refund":
            return Diagnosis(
                likely_cause="Customer is requesting a refund which cannot be automated.",
                evidence=["Ticket explicitly asks for a refund."],
                confidence=0.93,
                recommended_action="none",
                service_component="billing",
                requires_human=True,
            )
        if classification.category in {"data_deletion", "legal"}:
            return Diagnosis(
                likely_cause="Legal data deletion or privacy request.",
                evidence=["Ticket cites GDPR or deletion of personal data."],
                confidence=0.95,
                recommended_action="none",
                requires_human=True,
            )
        if classification.category == "security_abuse":
            return Diagnosis(
                likely_cause="Unrecognized login / possible account takeover.",
                evidence=["Customer reports a login they did not perform."],
                confidence=0.9,
                recommended_action="none",
                service_component="auth",
                requires_human=True,
            )
        if classification.category == "billing_dispute":
            return Diagnosis(
                likely_cause="Invoice or duplicate-charge dispute.",
                evidence=["Customer reports being charged twice or a failed invoice."],
                confidence=0.9,
                recommended_action="none",
                service_component="billing",
                requires_human=True,
            )
        if classification.category == "outage":
            return Diagnosis(
                likely_cause="Symptoms match a degraded API gateway.",
                evidence=["Customer reports 502/503/timeouts from the API."],
                confidence=0.84,
                recommended_action="none",
                service_component="api-gateway",
                requires_human=True,
            )
        # Allowlisted mutations that the policy may auto-execute.
        if "locked" in text:
            return Diagnosis(
                likely_cause="Identity locked after failed sign-in attempts.",
                evidence=[
                    "Customer reports lockout; lockout tool expected to confirm."
                ],
                confidence=0.92,
                recommended_action="unlock_account",
                service_component="auth",
            )
        if "verification email" in text:
            return Diagnosis(
                likely_cause="Verification email was not received.",
                evidence=["Customer asked to resend verification."],
                confidence=0.9,
                recommended_action="resend_verification_email",
                service_component="auth",
            )
        if "webhook" in text:
            return Diagnosis(
                likely_cause="Workspace webhook delivery is failing.",
                evidence=["Customer asked to retry a failed webhook."],
                confidence=0.88,
                recommended_action="retry_failed_webhook",
                service_component="webhooks",
            )
        if "cache" in text or ("dashboard" in text and "yesterday" in text):
            return Diagnosis(
                likely_cause="Stale workspace cache on usage dashboard.",
                evidence=["Customer reports dashboard not updating."],
                confidence=0.85,
                recommended_action="clear_workspace_cache",
                service_component="cache",
            )
        if "api key" in text:
            return Diagnosis(
                likely_cause="Workspace API key needs rotation after possible exposure.",
                evidence=["Customer requested a key rotation."],
                confidence=0.87,
                recommended_action="rotate_workspace_api_key",
                service_component="auth",
            )
        # Knowledge-only: reply from an article, no mutation.
        if classification.category == "how_to":
            article = kb_hits[0].title if kb_hits else "internal knowledge"
            return Diagnosis(
                likely_cause=f"How-to question answered by knowledge article ({article}).",
                evidence=["No broken account state required to answer."],
                confidence=0.9,
                recommended_action="none",
            )
        return Diagnosis(
            likely_cause="Insufficient detail to diagnose.",
            evidence=["Ticket text is vague."],
            confidence=0.3,
            recommended_action="none",
            requires_human=True,
        )

    def draft_reply(self, context: ReplyContext) -> str:
        """Fixed templates for escalate, verified fix, how-to, and fallback."""
        name = context.customer_name.split()[0]
        if context.escalate:
            return (
                f"Hi {name},\n\nThanks for writing in. I've gathered the details and passed this "
                "to a specialist who will follow up. I have not made billing, legal, or security "
                "changes from this ticket.\n\nNorthstar Support (automated assistant)"
            )
        if context.remediated and context.verified:
            return (
                f"Hi {name},\n\nI looked this up and applied a low-risk fix "
                f"({context.action}). I then re-checked the workspace "
                "and the issue appears resolved. "
                "Please try again and reply if anything still looks off.\n\n"
                "Northstar Support (automated assistant)"
            )
        if context.classification.category == "how_to" and context.kb_hits:
            hit = context.kb_hits[0]
            return (
                f"Hi {name},\n\nThis is documented in “{hit.title}”. {hit.snippet}\n\n"
                "Northstar Support (automated assistant)"
            )
        return (
            f"Hi {name},\n\nThanks for the ticket. I've recorded the details for the team.\n\n"
            "Northstar Support (automated assistant)"
        )
