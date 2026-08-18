"""Mock tool registry tests: read vs mutate, allowlist, and unknown tools."""

from src.models import AccountState
from src.tools import registry


def test_readonly_and_mutating_names():
    assert "get_customer" in registry.names(mutating=False)
    assert "unlock_account" in registry.names(mutating=True)
    assert "unlock_account" not in registry.names(mutating=False)


def test_mutating_tool_blocked_without_flag(seeded):
    result = registry.execute(
        seeded,
        name="unlock_account",
        args={"customer_id": "cust_acme"},
        run_id=None,
        ticket_id=None,
        allow_mutating=False,
    )
    assert result.ok is False
    assert "not allowed" in (result.error or "")
    state = seeded.get(AccountState, "cust_acme")
    assert state.locked is True


def test_unlock_account(seeded):
    result = registry.execute(
        seeded,
        name="unlock_account",
        args={"customer_id": "cust_acme"},
        run_id=None,
        ticket_id="TCK-1001",
        allow_mutating=True,
    )
    assert result.ok is True
    state = seeded.get(AccountState, "cust_acme")
    assert state.locked is False


def test_unknown_tool(seeded):
    result = registry.execute(
        seeded,
        name="issue_refund",
        args={},
        run_id=None,
        ticket_id=None,
        allow_mutating=True,
    )
    assert result.ok is False
    assert "unknown tool" in (result.error or "")


def test_get_service_status(seeded):
    result = registry.execute(
        seeded,
        name="get_service_status",
        args={},
        run_id=None,
        ticket_id=None,
        allow_mutating=False,
    )
    assert result.ok is True
    gateway = next(c for c in result.data["components"] if c["id"] == "api-gateway")
    assert gateway["status"] == "degraded"
