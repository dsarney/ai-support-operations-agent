"""Named tool registry with OpenAI function schemas and a mutating-tool safety check."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from src.models import AuditEvent
from src.schemas import ToolResult
from src.util import new_id

ToolFn = Callable[..., ToolResult]


@dataclass(frozen=True)
class ToolSpec:
    """One registered tool: schema for the LLM plus the Python function to execute."""

    name: str
    description: str
    mutating: bool
    parameters: dict[str, Any]
    fn: ToolFn


class ToolRegistry:
    """Decorator-based registry. Investigation can only execute tools with mutating=False."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    def register(
        self,
        name: str,
        description: str,
        *,
        mutating: bool = False,
        parameters: dict[str, Any] | None = None,
    ) -> Callable[[ToolFn], ToolFn]:
        def decorator(fn: ToolFn) -> ToolFn:
            self._tools[name] = ToolSpec(
                name=name,
                description=description,
                mutating=mutating,
                parameters=parameters or {"type": "object", "properties": {}},
                fn=fn,
            )
            return fn

        return decorator

    def get(self, name: str) -> ToolSpec | None:
        return self._tools.get(name)

    def names(self, *, mutating: bool | None = None) -> list[str]:
        specs = self._tools.values()
        if mutating is None:
            return sorted(spec.name for spec in specs)
        return sorted(spec.name for spec in specs if spec.mutating is mutating)

    def openai_tools(self, *, mutating: bool = False) -> list[dict[str, Any]]:
        """OpenAI function-calling schemas. Investigation always requests mutating=False."""
        tools = []
        for spec in self._tools.values():
            if spec.mutating != mutating:
                continue
            tools.append(
                {
                    "type": "function",
                    "function": {
                        "name": spec.name,
                        "description": spec.description,
                        "parameters": spec.parameters,
                    },
                }
            )
        return tools

    def execute(
        self,
        session: Session,
        *,
        name: str,
        args: dict[str, Any],
        run_id: str | None,
        ticket_id: str | None,
        allow_mutating: bool,
    ) -> ToolResult:
        spec = self._tools.get(name)
        if spec is None:
            result = ToolResult(ok=False, error=f"unknown tool '{name}'")
        elif spec.mutating and not allow_mutating:
            # Investigation stage sets allow_mutating=False so the LLM cannot mutate via tool choice.
            result = ToolResult(
                ok=False,
                error=f"mutating tool '{name}' is not allowed in this stage",
            )
        else:
            try:
                result = spec.fn(session, **(args or {}))
            except TypeError as exc:
                result = ToolResult(ok=False, error=f"invalid arguments: {exc}")
            except Exception as exc:  # noqa: BLE001 - tools must not crash the run
                result = ToolResult(ok=False, error=str(exc))

        session.add(
            # Every tool call is audited, including blocked mutating attempts.
            AuditEvent(
                id=new_id("aud"),
                run_id=run_id,
                ticket_id=ticket_id,
                event_type="tool_call",
                payload_json=_json(
                    {
                        "tool": name,
                        "args": args,
                        "mutating": bool(spec.mutating) if spec else False,
                        "allow_mutating": allow_mutating,
                        "result": result.to_payload(),
                    }
                ),
            )
        )
        session.flush()
        return result


def _json(payload: dict[str, Any]) -> str:
    import json

    return json.dumps(payload, default=str)
