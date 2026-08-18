"""Small helpers shared across the package."""

from __future__ import annotations

import uuid


def new_id(prefix: str) -> str:
    """Opaque id like `run_a1b2c3d4e5f6` for tickets, runs, steps, and audit events."""
    return f"{prefix}_{uuid.uuid4().hex[:12]}"
