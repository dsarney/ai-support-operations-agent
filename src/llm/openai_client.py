"""Live OpenAI client implementing the LLMClient protocol with structured outputs."""

from __future__ import annotations

import json
from typing import Any

from openai import OpenAI

from src.agent.prompts import (
    CLASSIFY_SYSTEM,
    DIAGNOSE_SYSTEM,
    INVESTIGATE_SYSTEM,
    REPLY_SYSTEM,
)
from src.llm.base import InvestigationContext, ReplyContext
from src.schemas import (
    Classification,
    Diagnosis,
    InvestigationDecision,
    KnowledgeHit,
)
from src.tools import registry


class OpenAIClient:
    """Classify, investigate, diagnose, and draft replies via the OpenAI API."""

    def __init__(self, api_key: str, model: str) -> None:
        if not api_key or api_key.startswith("your_"):
            # .env.example uses a placeholder; refuse to start rather than send a bogus key.
            raise RuntimeError(
                "OPENAI_API_KEY is missing. Copy .env.example to .env and set a real key."
            )
        self.model_name = model
        self._client = OpenAI(api_key=api_key)

    def classify(self, subject: str, body: str) -> Classification:
        completion = self._client.beta.chat.completions.parse(
            model=self.model_name,
            messages=[
                {"role": "system", "content": CLASSIFY_SYSTEM},
                {
                    "role": "user",
                    "content": f"Subject: {subject}\n\n{body}",
                },
            ],
            response_format=Classification,
        )
        parsed = completion.choices[0].message.parsed
        if parsed is None:
            raise RuntimeError("OpenAI returned an empty classification")
        return parsed

    def next_investigation_action(
        self, context: InvestigationContext
    ) -> InvestigationDecision:
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": INVESTIGATE_SYSTEM},
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "customer_id": context.customer_id,
                        "subject": context.subject,
                        "body": context.body,
                        "classification": context.classification.model_dump(),
                        "knowledge": [hit.model_dump() for hit in context.kb_hits],
                        "prior_tool_results": context.prior_steps,
                        "available_tools": context.available_tools,
                    },
                    default=str,
                ),
            },
        ]
        response = self._client.chat.completions.create(
            model=self.model_name,
            messages=messages,
            tools=registry.openai_tools(mutating=False),
            tool_choice="auto",
        )
        message = response.choices[0].message
        # No tool call means the model thinks it has enough evidence.
        if not message.tool_calls:
            return InvestigationDecision(
                done=True,
                summary=message.content or "Investigation complete",
            )
        call = message.tool_calls[
            0
        ]  # pipeline executes one investigation tool per turn
        try:
            args = json.loads(call.function.arguments or "{}")
        except json.JSONDecodeError:
            args = {}
        return InvestigationDecision(
            done=False,
            tool_name=call.function.name,
            args=args if isinstance(args, dict) else {},
            summary=f"Calling {call.function.name}",
        )

    def diagnose(
        self,
        subject: str,
        body: str,
        classification: Classification,
        kb_hits: list[KnowledgeHit],
        evidence: list[dict],
    ) -> Diagnosis:
        completion = self._client.beta.chat.completions.parse(
            model=self.model_name,
            messages=[
                {"role": "system", "content": DIAGNOSE_SYSTEM},
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "subject": subject,
                            "body": body,
                            "classification": classification.model_dump(),
                            "knowledge": [hit.model_dump() for hit in kb_hits],
                            "evidence": evidence,
                        },
                        default=str,
                    ),
                },
            ],
            response_format=Diagnosis,
        )
        parsed = completion.choices[0].message.parsed
        if parsed is None:
            raise RuntimeError("OpenAI returned an empty diagnosis")
        return parsed

    def draft_reply(self, context: ReplyContext) -> str:
        completion = self._client.chat.completions.create(
            model=self.model_name,
            messages=[
                {"role": "system", "content": REPLY_SYSTEM},
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "customer_name": context.customer_name,
                            "subject": context.subject,
                            "body": context.body,
                            "classification": context.classification.model_dump(),
                            "diagnosis": context.diagnosis.model_dump(),
                            "policy_reasons": context.policy_reasons,
                            "knowledge": [hit.model_dump() for hit in context.kb_hits],
                            "remediated": context.remediated,
                            "verified": context.verified,
                            "escalate": context.escalate,
                            "action": context.action,
                        },
                        default=str,
                    ),
                },
            ],
        )
        return (completion.choices[0].message.content or "").strip()
