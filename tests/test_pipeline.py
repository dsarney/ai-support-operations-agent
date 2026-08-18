"""End-to-end pipeline tests: auto-resolve, escalate, how-to, and incident clustering."""

from src.agent.pipeline import AgentPipeline
from src.llm.fake import FakeLLM
from src.models import AccountState, IncidentTicket, Ticket


def test_pipeline_unlocks_lockout_ticket(settings, seeded):
    run = AgentPipeline(seeded, settings, FakeLLM()).run("TCK-1001")
    seeded.commit()
    ticket = seeded.get(Ticket, "TCK-1001")
    state = seeded.get(AccountState, "cust_acme")
    assert run.outcome == "resolved"
    assert ticket.status == "resolved"
    assert state.locked is False
    assert any(step.stage == "verify" for step in run.steps)
    assert run.reply_text


def test_pipeline_escalates_refund(settings, seeded):
    run = AgentPipeline(seeded, settings, FakeLLM()).run("TCK-1009")
    seeded.commit()
    ticket = seeded.get(Ticket, "TCK-1009")
    assert run.outcome == "escalated"
    assert ticket.status == "escalated"
    assert seeded.get(AccountState, "cust_summit") is not None


def test_pipeline_how_to_resolves_without_mutation(settings, seeded):
    run = AgentPipeline(seeded, settings, FakeLLM()).run("TCK-1006")
    seeded.commit()
    ticket = seeded.get(Ticket, "TCK-1006")
    assert run.outcome == "resolved"
    assert ticket.status == "resolved"
    assert run.remediations == []


def test_outage_tickets_share_an_incident(settings, seeded):
    llm = FakeLLM()
    pipeline = AgentPipeline(seeded, settings, llm)
    for ticket_id in ("TCK-1014", "TCK-1015", "TCK-1016", "TCK-1017"):
        run = pipeline.run(ticket_id)
        assert run.outcome == "escalated"
    seeded.commit()
    links = seeded.query(IncidentTicket).all()
    incident_ids = {link.incident_id for link in links}
    assert len(incident_ids) == 1
    assert {link.ticket_id for link in links} >= {
        "TCK-1014",
        "TCK-1015",
        "TCK-1016",
        "TCK-1017",
    }
