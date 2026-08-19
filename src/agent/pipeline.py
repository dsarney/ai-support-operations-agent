"""Staged agent run: classify, retrieve, investigate, diagnose, policy, remediate, reply, audit."""

from __future__ import annotations

import json
from collections.abc import Callable

from sqlalchemy.orm import Session

from src.config import Settings
from src.db import utcnow
from src.incidents.correlator import correlate_ticket
from src.knowledge.search import search_knowledge
from src.llm.base import InvestigationContext, LLMClient, ReplyContext
from src.models import (
    AgentRun,
    AgentStep,
    AuditEvent,
    Customer,
    RemediationAction,
    Ticket,
    TicketMessage,
)
from src.policy.engine import evaluate_policy
from src.schemas import Classification, Diagnosis, KnowledgeHit, PolicyDecision
from src.tools import registry as default_registry
from src.tools.registry import ToolRegistry
from src.util import new_id

# After a mutating tool runs, re-read state with a read-only tool and require this predicate.
VERIFY_CHECKS: dict[str, tuple[str, Callable[[dict], bool]]] = {
    "unlock_account": ("get_login_lockout", lambda data: data.get("locked") is False),
    "resend_verification_email": (
        "get_login_lockout",
        lambda data: data.get("verification_email_resent_at") is not None,
    ),
    "rotate_workspace_api_key": (
        "get_workspace_integrations",
        lambda data: data.get("api_key_rotated_at") is not None,
    ),
    "retry_failed_webhook": (
        "get_workspace_integrations",
        lambda data: data.get("webhook_status") == "healthy",
    ),
    "clear_workspace_cache": (
        "get_workspace_integrations",
        lambda data: data.get("cache_stale") is False,
    ),
}


class AgentPipeline:
    """Run one ticket through the full support-ops pipeline and persist an audit trail."""

    def __init__(
        self,
        session: Session,
        settings: Settings,
        llm: LLMClient,
        tools: ToolRegistry | None = None,
    ) -> None:
        self.session = session
        self.settings = settings
        self.llm = llm
        self.tools = tools or default_registry
        self._seq = 0

    def run(self, ticket_id: str) -> AgentRun:
        """Execute the pipeline. On unexpected failure, reopen the ticket and record the error."""
        ticket = self.session.get(Ticket, ticket_id)
        if ticket is None:
            raise ValueError(f"ticket '{ticket_id}' not found")
        customer = self.session.get(Customer, ticket.customer_id)
        if customer is None:
            raise ValueError(f"customer '{ticket.customer_id}' not found")

        run = AgentRun(
            id=new_id("run"),
            ticket_id=ticket.id,
            status="running",
            model=self.llm.model_name,
        )
        self.session.add(run)
        ticket.status = "in_progress"
        ticket.updated_at = utcnow()
        self.session.commit()
        self._seq = 0

        try:
            self._execute(ticket, customer, run)
        except Exception as exc:  # noqa: BLE001 - a failed run must not crash the CLI/dashboard
            run.status = "failed"
            run.outcome = "failed"
            run.error = str(exc)
            run.finished_at = utcnow()
            ticket.status = "open"  # leave the ticket retryable
            self._audit(run, ticket, "run_failed", {"error": str(exc)})
            self.session.commit()
        return run

    def _execute(self, ticket: Ticket, customer: Customer, run: AgentRun) -> None:
        """Classify → retrieve KB → investigate → diagnose → policy → maybe remediate → reply."""
        self._normalize(ticket, customer, run)
        classification = self._classify(ticket, run)
        kb_hits = self._retrieve(ticket, run)
        evidence = self._investigate(ticket, customer, run, classification, kb_hits)
        diagnosis = self._diagnose(ticket, run, classification, kb_hits, evidence)
        policy = self._apply_policy(ticket, customer, run, classification, diagnosis)
        remediated, verified, policy = self._maybe_remediate(
            ticket, customer, run, policy
        )
        self._draft_reply(
            ticket,
            customer,
            run,
            classification,
            diagnosis,
            kb_hits,
            policy,
            remediated,
            verified,
        )
        self._apply_outcome(ticket, run, policy, remediated, verified)
        self._correlate(ticket, run, diagnosis)

        run.status = "completed"
        run.finished_at = utcnow()
        ticket.updated_at = utcnow()
        self.session.commit()

    def _normalize(self, ticket: Ticket, customer: Customer, run: AgentRun) -> None:
        self._log_step(
            run,
            "normalize",
            f"Normalized {ticket.id} from {ticket.channel} for {customer.company}",
            output={
                "ticket_id": ticket.id,
                "customer_id": customer.id,
                "channel": ticket.channel,
            },
        )

    def _classify(self, ticket: Ticket, run: AgentRun) -> Classification:
        classification = self.llm.classify(ticket.subject, ticket.body)
        ticket.category = classification.category
        ticket.priority = classification.priority
        ticket.urgency = classification.urgency
        ticket.sentiment = classification.sentiment
        ticket.pii_likely = classification.pii_likely
        ticket.classification_confidence = classification.confidence
        run.classification_json = classification.model_dump_json()
        self._log_step(
            run,
            "classify",
            f"{classification.category} / {classification.priority} "
            f"({classification.confidence:.2f})",
            output=classification.model_dump(),
        )
        return classification

    def _retrieve(self, ticket: Ticket, run: AgentRun) -> list[KnowledgeHit]:
        kb_hits = search_knowledge(
            self.session, f"{ticket.subject} {ticket.body}", limit=5
        )
        ticket.kb_article_ids_json = json.dumps([hit.article_id for hit in kb_hits])
        self._log_step(
            run,
            "retrieve",
            f"{len(kb_hits)} knowledge hits",
            output={"hits": [hit.model_dump() for hit in kb_hits]},
        )
        return kb_hits

    def _diagnose(
        self,
        ticket: Ticket,
        run: AgentRun,
        classification: Classification,
        kb_hits: list[KnowledgeHit],
        evidence: list[dict],
    ) -> Diagnosis:
        diagnosis = self.llm.diagnose(
            ticket.subject, ticket.body, classification, kb_hits, evidence
        )
        run.diagnosis_json = diagnosis.model_dump_json()
        self._log_step(
            run,
            "diagnose",
            f"{diagnosis.likely_cause} → {diagnosis.recommended_action}",
            output=diagnosis.model_dump(),
        )
        return diagnosis

    def _apply_policy(
        self,
        ticket: Ticket,
        customer: Customer,
        run: AgentRun,
        classification: Classification,
        diagnosis: Diagnosis,
    ) -> PolicyDecision:
        policy = evaluate_policy(
            classification=classification,
            diagnosis=diagnosis,
            ticket=ticket,
            customer=customer,
            auto_remediate=self.settings.auto_remediate,
            classify_threshold=self.settings.classify_confidence_threshold,
            diagnose_threshold=self.settings.diagnose_confidence_threshold,
            mutating_already_done=False,
        )
        run.policy_json = policy.model_dump_json()
        self._log_step(
            run,
            "policy",
            "; ".join(policy.reasons) or "policy evaluated",
            output=policy.model_dump(),
        )
        self._audit(run, ticket, "policy_decision", policy.model_dump())
        return policy

    def _maybe_remediate(
        self,
        ticket: Ticket,
        customer: Customer,
        run: AgentRun,
        policy: PolicyDecision,
    ) -> tuple[bool, bool, PolicyDecision]:
        """Run the allowlisted mutating tool only after the deterministic policy gate."""
        remediated = False
        verified = False
        if policy.allow_auto_remediation and policy.allowed_action:
            result = self.tools.execute(
                self.session,
                name=policy.allowed_action,
                args={"customer_id": customer.id},
                run_id=run.id,
                ticket_id=ticket.id,
                allow_mutating=True,
            )
            action_row = RemediationAction(
                id=new_id("act"),
                run_id=run.id,
                ticket_id=ticket.id,
                action_type=policy.allowed_action,
                risk=policy.risk,
                result_json=json.dumps(result.to_payload()),
                verified=False,
            )
            self.session.add(action_row)
            self._log_step(
                run,
                "remediate",
                f"{policy.allowed_action}: {'ok' if result.ok else result.error}",
                tool_name=policy.allowed_action,
                tool_args={"customer_id": customer.id},
                tool_result=result.to_payload(),
            )
            remediated = result.ok
            if result.ok:
                verified = self._verify(run, ticket, customer, policy.allowed_action)
                action_row.verified = verified
            else:
                policy = policy.model_copy(
                    update={
                        "escalate": True,
                        "reasons": [*policy.reasons, "remediation tool failed"],
                    }
                )
        return remediated, verified, policy

    def _draft_reply(
        self,
        ticket: Ticket,
        customer: Customer,
        run: AgentRun,
        classification: Classification,
        diagnosis: Diagnosis,
        kb_hits: list[KnowledgeHit],
        policy: PolicyDecision,
        remediated: bool,
        verified: bool,
    ) -> None:
        # A mutation that did not verify is treated as escalate so we never claim a fix.
        reply = self.llm.draft_reply(
            ReplyContext(
                customer_name=customer.name,
                subject=ticket.subject,
                body=ticket.body,
                classification=classification,
                diagnosis=diagnosis,
                policy_reasons=policy.reasons,
                kb_hits=kb_hits,
                remediated=remediated,
                verified=verified,
                escalate=policy.escalate or (remediated and not verified),
                action=policy.allowed_action,
            )
        )
        run.reply_text = reply
        self.session.add(
            TicketMessage(
                id=new_id("msg"), ticket_id=ticket.id, author="agent", body=reply
            )
        )
        self._log_step(run, "reply", "Drafted customer reply", output={"reply": reply})

    def _apply_outcome(
        self,
        ticket: Ticket,
        run: AgentRun,
        policy: PolicyDecision,
        remediated: bool,
        verified: bool,
    ) -> None:
        """Resolve only after a verified mutation or a knowledge-only reply; otherwise escalate."""
        escalate = policy.escalate or (remediated and not verified)
        if remediated and verified and not escalate:
            ticket.status = "resolved"
            run.outcome = "resolved"
        elif escalate:
            ticket.status = "escalated"
            run.outcome = "escalated"
            self._log_step(
                run,
                "escalate",
                "Escalated to a human",
                output={"reasons": policy.reasons},
            )
        elif policy.resolve_with_reply:
            ticket.status = "resolved"
            run.outcome = "resolved"
        else:
            ticket.status = "escalated"
            run.outcome = "escalated"

    def _correlate(self, ticket: Ticket, run: AgentRun, diagnosis: Diagnosis) -> None:
        incident = correlate_ticket(self.session, ticket, diagnosis)
        if incident is not None:
            self._log_step(
                run,
                "correlate",
                f"Linked to incident {incident.id}: {incident.title}",
                output={"incident_id": incident.id, "title": incident.title},
            )

    def _investigate(
        self,
        ticket: Ticket,
        customer: Customer,
        run: AgentRun,
        classification: Classification,
        kb_hits: list[KnowledgeHit],
    ) -> list[dict]:
        """Loop of LLM-chosen read-only tool calls, capped by max_investigate_steps."""
        evidence: list[dict] = []
        readonly = self.tools.names(mutating=False)
        # LLM chooses the next read-only tool; mutating tools are blocked at the registry.
        for _ in range(self.settings.max_investigate_steps):
            decision = self.llm.next_investigation_action(
                InvestigationContext(
                    customer_id=customer.id,
                    subject=ticket.subject,
                    body=ticket.body,
                    classification=classification,
                    kb_hits=kb_hits,
                    prior_steps=evidence,
                    available_tools=readonly,
                )
            )
            if decision.done or not decision.tool_name:
                self._log_step(
                    run,
                    "investigate",
                    decision.summary or "Investigation complete",
                    output=decision.model_dump(),
                )
                break
            result = self.tools.execute(
                self.session,
                name=decision.tool_name,
                args=decision.args,
                run_id=run.id,
                ticket_id=ticket.id,
                allow_mutating=False,
            )
            record = {
                "tool": decision.tool_name,
                "args": decision.args,
                "result": result.to_payload(),
            }
            evidence.append(record)
            self._log_step(
                run,
                "investigate",
                decision.summary or decision.tool_name,
                tool_name=decision.tool_name,
                tool_args=decision.args,
                tool_result=result.to_payload(),
            )
        return evidence

    def _verify(
        self, run: AgentRun, ticket: Ticket, customer: Customer, action: str
    ) -> bool:
        """Re-query account state and confirm the mutation actually took effect."""
        check = VERIFY_CHECKS.get(action)
        if check is None:
            self._log_step(
                run, "verify", f"No verifier for {action}", output={"verified": False}
            )
            return False
        tool_name, predicate = check
        spec = self.tools.get(tool_name)
        args: dict = {}
        if spec and "customer_id" in spec.parameters.get("properties", {}):
            args = {"customer_id": customer.id}
        result = self.tools.execute(
            self.session,
            name=tool_name,
            args=args,
            run_id=run.id,
            ticket_id=ticket.id,
            allow_mutating=False,
        )
        verified = bool(result.ok and predicate(result.data))
        self._log_step(
            run,
            "verify",
            f"{action} verified" if verified else f"{action} did not verify",
            tool_name=tool_name,
            tool_args=args,
            tool_result=result.to_payload(),
            output={"verified": verified},
        )
        return verified

    def _log_step(
        self,
        run: AgentRun,
        stage: str,
        summary: str,
        *,
        tool_name: str | None = None,
        tool_args: dict | None = None,
        tool_result: dict | None = None,
        output: dict | None = None,
        latency_ms: int = 0,
        tokens: int = 0,
    ) -> AgentStep:
        """Persist one ordered pipeline stage so the dashboard can replay the run.

        Commit immediately so the dashboard can show progress while later stages
        (LLM calls, tools) are still running.
        """
        step = AgentStep(
            id=new_id("step"),
            run_id=run.id,
            seq=self._seq,
            stage=stage,
            summary=summary,
            tool_name=tool_name,
            tool_args_json=json.dumps(tool_args) if tool_args is not None else None,
            tool_result_json=(
                json.dumps(tool_result) if tool_result is not None else None
            ),
            output_json=json.dumps(output or {}, default=str),
            latency_ms=latency_ms,
            tokens=tokens,
        )
        self.session.add(step)
        self.session.commit()
        self._seq += 1
        return step

    def _audit(
        self, run: AgentRun, ticket: Ticket, event_type: str, payload: dict
    ) -> None:
        """Append a durable audit event independent of the per-step run log."""
        self.session.add(
            AuditEvent(
                id=new_id("aud"),
                run_id=run.id,
                ticket_id=ticket.id,
                event_type=event_type,
                payload_json=json.dumps(payload, default=str),
            )
        )
