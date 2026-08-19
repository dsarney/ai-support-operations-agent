"""Incident clustering for related tickets sharing a degraded component or articles."""

from src.incidents.correlator import correlate_ticket

__all__ = ["correlate_ticket"]
