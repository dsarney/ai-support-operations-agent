"""Mock Northstar business tools. Mutating tools only run when the policy gate allows them."""

from __future__ import annotations

from src.db import utcnow
from src.knowledge.search import search_knowledge as kb_search
from src.models import (
    AccountState,
    Customer,
    Invoice,
    ServiceComponent,
    Subscription,
)
from src.schemas import ToolResult
from src.tools.registry import ToolRegistry

registry = ToolRegistry()

_CUSTOMER_PARAM = {
    "type": "object",
    "properties": {"customer_id": {"type": "string"}},
    "required": ["customer_id"],
    "additionalProperties": False,
}


def _customer_payload(customer: Customer) -> dict:
    return {
        "id": customer.id,
        "name": customer.name,
        "email": customer.email,
        "company": customer.company,
        "plan": customer.plan,
    }


@registry.register(
    "get_customer",
    "Look up a Northstar customer by id.",
    parameters=_CUSTOMER_PARAM,
)
def get_customer(session, customer_id: str) -> ToolResult:
    customer = session.get(Customer, customer_id)
    if customer is None:
        return ToolResult(ok=False, error=f"customer '{customer_id}' not found")
    return ToolResult(ok=True, data=_customer_payload(customer))


@registry.register(
    "get_subscription",
    "Return the customer's subscription status, plan, and seats.",
    parameters=_CUSTOMER_PARAM,
)
def get_subscription(session, customer_id: str) -> ToolResult:
    sub = session.query(Subscription).filter_by(customer_id=customer_id).one_or_none()
    if sub is None:
        return ToolResult(ok=False, error="subscription not found")
    return ToolResult(
        ok=True,
        data={
            "id": sub.id,
            "status": sub.status,
            "plan": sub.plan,
            "seats": sub.seats,
            "renews_on": sub.renews_on,
        },
    )


@registry.register(
    "get_recent_invoices",
    "List recent invoices for a customer.",
    parameters=_CUSTOMER_PARAM,
)
def get_recent_invoices(session, customer_id: str) -> ToolResult:
    invoices = session.query(Invoice).filter_by(customer_id=customer_id).all()
    return ToolResult(
        ok=True,
        data={
            "invoices": [
                {
                    "id": inv.id,
                    "amount_cents": inv.amount_cents,
                    "status": inv.status,
                    "period": inv.period,
                }
                for inv in invoices
            ]
        },
    )


@registry.register(
    "get_service_status",
    "Check Northstar component health. Omit component to list all.",
    parameters={
        "type": "object",
        "properties": {"component": {"type": "string"}},
        "additionalProperties": False,
    },
)
def get_service_status(session, component: str | None = None) -> ToolResult:
    query = session.query(ServiceComponent)
    if component:
        query = query.filter(ServiceComponent.id == component)
    rows = query.all()
    if component and not rows:
        return ToolResult(ok=False, error=f"unknown component '{component}'")
    return ToolResult(
        ok=True,
        data={
            "components": [
                {
                    "id": row.id,
                    "name": row.name,
                    "status": row.status,
                    "message": row.message,
                }
                for row in rows
            ]
        },
    )


@registry.register(
    "get_login_lockout",
    "Check whether the customer's identity is locked out of sign-in.",
    parameters=_CUSTOMER_PARAM,
)
def get_login_lockout(session, customer_id: str) -> ToolResult:
    state = session.get(AccountState, customer_id)
    if state is None:
        return ToolResult(ok=False, error="account state not found")
    return ToolResult(
        ok=True,
        data={
            "locked": state.locked,
            "lock_reason": state.lock_reason,
            "failed_sign_in_attempts": state.failed_sign_in_attempts,
            "email_verified": state.email_verified,
            "verification_email_resent_at": (
                state.verification_email_resent_at.isoformat()
                if state.verification_email_resent_at
                else None
            ),
        },
    )


@registry.register(
    "get_workspace_integrations",
    "Return webhook delivery state, API key prefix, and cache freshness.",
    parameters=_CUSTOMER_PARAM,
)
def get_workspace_integrations(session, customer_id: str) -> ToolResult:
    state = session.get(AccountState, customer_id)
    if state is None:
        return ToolResult(ok=False, error="account state not found")
    return ToolResult(
        ok=True,
        data={
            "webhook_url": state.webhook_url,
            "webhook_status": state.webhook_status,
            "webhook_last_error": state.webhook_last_error,
            "api_key_prefix": state.api_key_prefix,
            "api_key_rotated_at": (
                state.api_key_rotated_at.isoformat()
                if state.api_key_rotated_at
                else None
            ),
            "cache_stale": state.cache_stale,
        },
    )


@registry.register(
    "search_knowledge",
    "Search the internal Northstar knowledge base.",
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "limit": {"type": "integer"},
        },
        "required": ["query"],
        "additionalProperties": False,
    },
)
def search_knowledge_tool(session, query: str, limit: int = 5) -> ToolResult:
    hits = kb_search(session, query, limit=limit)
    return ToolResult(ok=True, data={"hits": [hit.model_dump() for hit in hits]})


@registry.register(
    "unlock_account",
    "Unlock a customer identity locked after failed sign-in attempts.",
    mutating=True,
    parameters=_CUSTOMER_PARAM,
)
def unlock_account(session, customer_id: str) -> ToolResult:
    state = session.get(AccountState, customer_id)
    if state is None:
        return ToolResult(ok=False, error="account state not found")
    state.locked = False
    state.lock_reason = None
    state.failed_sign_in_attempts = 0
    session.flush()
    return ToolResult(ok=True, data={"locked": False, "customer_id": customer_id})


@registry.register(
    "resend_verification_email",
    "Queue a new workspace verification email to the customer address.",
    mutating=True,
    parameters=_CUSTOMER_PARAM,
)
def resend_verification_email(session, customer_id: str) -> ToolResult:
    state = session.get(AccountState, customer_id)
    if state is None:
        return ToolResult(ok=False, error="account state not found")
    state.verification_email_resent_at = utcnow()
    session.flush()
    return ToolResult(
        ok=True,
        data={
            "resent_at": state.verification_email_resent_at.isoformat(),
            "customer_id": customer_id,
        },
    )


@registry.register(
    "rotate_workspace_api_key",
    "Rotate the workspace live API key. The previous secret is invalidated.",
    mutating=True,
    parameters=_CUSTOMER_PARAM,
)
def rotate_workspace_api_key(session, customer_id: str) -> ToolResult:
    state = session.get(AccountState, customer_id)
    if state is None:
        return ToolResult(ok=False, error="account state not found")
    suffix = customer_id.replace("cust_", "")[:4]
    # Prefix only — the full secret is never returned to the agent or ticket reply.
    state.api_key_prefix = f"nsk_live_{suffix}_rot"
    state.api_key_rotated_at = utcnow()
    session.flush()
    return ToolResult(
        ok=True,
        data={
            "api_key_prefix": state.api_key_prefix,
            "rotated_at": state.api_key_rotated_at.isoformat(),
            "note": "Full secret is not returned to the agent or ticket reply.",
        },
    )


@registry.register(
    "retry_failed_webhook",
    "Retry the latest failed outbound webhook delivery for a workspace.",
    mutating=True,
    parameters=_CUSTOMER_PARAM,
)
def retry_failed_webhook(session, customer_id: str) -> ToolResult:
    state = session.get(AccountState, customer_id)
    if state is None:
        return ToolResult(ok=False, error="account state not found")
    if not state.webhook_url:
        return ToolResult(ok=False, error="workspace has no webhook URL")
    state.webhook_status = "healthy"
    state.webhook_last_error = None
    session.flush()
    return ToolResult(
        ok=True,
        data={"webhook_status": "healthy", "webhook_url": state.webhook_url},
    )


@registry.register(
    "clear_workspace_cache",
    "Drop stale cached dashboard views for a workspace.",
    mutating=True,
    parameters=_CUSTOMER_PARAM,
)
def clear_workspace_cache(session, customer_id: str) -> ToolResult:
    state = session.get(AccountState, customer_id)
    if state is None:
        return ToolResult(ok=False, error="account state not found")
    state.cache_stale = False
    session.flush()
    return ToolResult(ok=True, data={"cache_stale": False, "customer_id": customer_id})
