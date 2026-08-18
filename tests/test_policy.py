"""Policy-engine unit tests. These never construct an LLM."""

from src.models import Customer, Ticket
from src.policy.engine import evaluate_policy
from src.schemas import Classification, Diagnosis


def _decision(
    category="access",
    priority="medium",
    confidence=0.9,
    action="unlock_account",
    diag_confidence=0.9,
    plan="team",
    subject="Need help",
    body="Please unlock my account after too many password retries.",
    requires_human=False,
    service_component=None,
    auto=True,
):
    customer = Customer(
        id="cust_x",
        name="Ada",
        email="ada@example.test",
        company="Example",
        plan=plan,
    )
    ticket = Ticket(
        id="TCK-1",
        customer_id="cust_x",
        subject=subject,
        body=body,
        channel="email",
        status="open",
    )
    classification = Classification(
        category=category,
        priority=priority,
        urgency="medium",
        sentiment="neutral",
        confidence=confidence,
        summary="test",
    )
    diagnosis = Diagnosis(
        likely_cause="test",
        evidence=["e"],
        confidence=diag_confidence,
        recommended_action=action,
        service_component=service_component,
        requires_human=requires_human,
    )
    return evaluate_policy(
        classification=classification,
        diagnosis=diagnosis,
        ticket=ticket,
        customer=customer,
        auto_remediate=auto,
        classify_threshold=0.55,
        diagnose_threshold=0.6,
    )


def test_allowlisted_unlock_is_auto():
    decision = _decision()
    assert decision.allow_auto_remediation is True
    assert decision.escalate is False
    assert decision.allowed_action == "unlock_account"


def test_how_to_resolves_with_reply():
    decision = _decision(
        category="how_to", action="none", body="How do I invite teammates?"
    )
    assert decision.allow_auto_remediation is False
    assert decision.resolve_with_reply is True
    assert decision.escalate is False


def test_refund_escalates():
    decision = _decision(
        category="refund",
        action="none",
        subject="Refund August",
        body="Issue a full refund for August immediately.",
    )
    assert decision.escalate is True
    assert decision.allow_auto_remediation is False


def test_denied_action_escalates():
    decision = _decision(action="issue_refund", category="billing")
    assert decision.escalate is True
    assert "never automated" in " ".join(decision.reasons)


def test_unknown_action_escalates():
    decision = _decision(action="restart_production")
    assert decision.escalate is True


def test_low_confidence_escalates():
    decision = _decision(confidence=0.2, action="none", category="other")
    assert decision.escalate is True


def test_gdpr_text_escalates():
    decision = _decision(
        category="access",
        action="unlock_account",
        body="Under GDPR please delete all my data from backups.",
    )
    assert decision.escalate is True


def test_takeover_escalates():
    decision = _decision(
        category="access",
        action="unlock_account",
        body="I didn't log in from that country. I think we were hacked.",
    )
    assert decision.escalate is True


def test_enterprise_critical_nontrivial_escalates():
    decision = _decision(
        plan="enterprise",
        priority="critical",
        action="rotate_workspace_api_key",
        body="Please rotate the key, this is blocking production.",
    )
    assert decision.escalate is True


def test_enterprise_critical_unlock_still_allowed():
    decision = _decision(
        plan="enterprise",
        priority="critical",
        action="unlock_account",
        body="Locked out after password retries.",
    )
    assert decision.allow_auto_remediation is True


def test_outage_escalates():
    decision = _decision(
        category="outage",
        action="none",
        body="API returning 502 from the gateway.",
        service_component="api-gateway",
    )
    assert decision.escalate is True


def test_auto_remediate_flag_disables_mutation():
    decision = _decision(auto=False)
    assert decision.allow_auto_remediation is False
