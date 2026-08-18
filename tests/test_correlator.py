"""Incident correlator tests: degraded components open a shared incident."""

from src.incidents.correlator import correlate_ticket
from src.models import Incident, Ticket
from src.schemas import Diagnosis


def test_degraded_component_opens_incident(seeded):
    ticket = seeded.get(Ticket, "TCK-1014")
    ticket.category = "outage"
    diagnosis = Diagnosis(
        likely_cause="API gateway 502s",
        evidence=["502"],
        confidence=0.8,
        recommended_action="none",
        service_component="api-gateway",
        requires_human=True,
    )
    incident = correlate_ticket(seeded, ticket, diagnosis)
    seeded.commit()
    assert incident is not None
    assert incident.component_id == "api-gateway"
    assert seeded.query(Incident).count() == 1
