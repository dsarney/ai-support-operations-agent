"""Small helpers shared across the package."""

from __future__ import annotations

import json
import uuid
from typing import Any


def new_id(prefix: str) -> str:
    """Opaque id like `run_a1b2c3d4e5f6` for tickets, runs, steps, and audit events."""
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def loads_dict(raw: str | None) -> dict[str, Any]:
    """Parse a JSON object; invalid payloads and non-dicts become ``{}``."""
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def loads_list(raw: str | None) -> list[Any]:
    """Parse a JSON array; invalid payloads and non-lists become ``[]``."""
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []
