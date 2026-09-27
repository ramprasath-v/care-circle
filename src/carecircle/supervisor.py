"""Explicit two-specialist orchestration and policy-safe response assembly."""
import asyncio
import json
import logging
from time import perf_counter
from typing import Any, Protocol
from uuid import uuid4

from strands import Agent
from strands.models import BedrockModel

from carecircle.agents.medication import MedicationAgent
from carecircle.agents.triage import TriageAgent
from carecircle.config import Settings
from carecircle.prompts import TRIAGE_PROMPT
from carecircle.providers.medication import InMemoryMedicationProvider
from carecircle.schemas import (
    CareRequest, CareResponse, Evidence, MedicationAssessment, ProposedAction, TriageResult,
)

logger = logging.getLogger("carecircle")


def log_event(event: str, **fields: Any) -> None:
    logger.info(json.dumps({"event": event, **fields}))


class TriageSpecialist(Protocol):
    async def assess(self, request: CareRequest) -> TriageResult: ...


class MedicationSpecialist(Protocol):
    async def assess(self, household_id: str) -> MedicationAssessment: ...


def build_specialists(settings: Settings) -> tuple[TriageAgent, MedicationAgent]:
    """Build exactly the two Phase 2 specialists with isolated responsibilities."""
    model = BedrockModel(model_id=settings.bedrock_model_id, region_name=settings.aws_region)

    def triage_factory() -> Agent:
        return Agent(
            name="triage_agent",
            description="Extracts safety and medication-routing signals for deterministic policy evaluation.",
            model=model,
            system_prompt=TRIAGE_PROMPT,
            callback_handler=None,
            tools=[],
        )

    return TriageAgent(triage_factory), MedicationAgent(InMemoryMedicationProvider())


class CareCircleSupervisor:
    def __init__(
        self,
        triage_agent: TriageSpecialist,
        medication_agent: MedicationSpecialist,
        timeout_seconds: float = 60,
    ):
        self._triage = triage_agent
        self._medication = medication_agent
        self._timeout_seconds = timeout_seconds

    async def _invoke_specialist(
        self, name: str, invocation: Any, request: CareRequest, incident_id: str
    ) -> Any:
        started = perf_counter()
        outcome = "failure"
        try:
            result = await invocation
            outcome = "success"
            return result
        except BaseException:
            raise
        finally:
            log_event(
                "specialist_completed",
                trace_id=incident_id,
                session_id=request.session_id,
                incident_id=incident_id,
                specialist=name,
                specialist_latency_ms=round((perf_counter() - started) * 1000, 2),
                outcome=outcome,
            )

    async def coordinate(self, request: CareRequest) -> CareResponse:
        started = perf_counter()
        incident_id = str(uuid4())
        outcome = "success"
        failure_type = None
        selected: list[str] = []
        policy_outcome = "not_evaluated"
        try:
            async with asyncio.timeout(self._timeout_seconds):
                selected.append("triage")
                triage = await self._invoke_specialist(
                    "triage", self._triage.assess(request), request, incident_id
                )
                policy_outcome = "emergency_stop" if triage.stop_normal_orchestration else (
                    "caregiver_review" if triage.incident_requires_review else "normal"
                )

                if triage.stop_normal_orchestration:
                    return self._emergency_response(incident_id, triage)

                evidence = list(triage.evidence)
                medication = None
                if triage.medication_related:
                    selected.append("medication")
                    medication = await self._invoke_specialist(
                        "medication", self._medication.assess(request.household_id), request, incident_id
                    )
                    evidence.extend(medication.evidence)

                return self._normal_response(incident_id, triage, evidence, medication)
        except Exception as exc:
            outcome = "fallback"
            failure_type = type(exc).__name__
            policy_outcome = "safe_fallback"
            return self._fallback_response(incident_id)
        finally:
            log_event(
                "supervisor_completed",
                trace_id=incident_id,
                session_id=request.session_id,
                incident_id=incident_id,
                selected_specialists=selected,
                policy_outcome=policy_outcome,
                latency_ms=round((perf_counter() - started) * 1000, 2),
                outcome=outcome,
                failure_type=failure_type,
            )

    @staticmethod
    def _action(description: str, action_type: str = "notify_primary_caregiver") -> ProposedAction:
        return ProposedAction(
            action_id=str(uuid4()), type=action_type, description=description,
            requires_confirmation=True,
        )

    def _emergency_response(self, incident_id: str, triage: TriageResult) -> CareResponse:
        return CareResponse(
            incident_id=incident_id,
            summary=triage.recommended_next_step,
            risk_level="high",
            evidence=triage.evidence,
            proposed_actions=[self._action(
                "Ask a caregiver to follow the configured household emergency plan and seek appropriate human help.",
                "follow_household_emergency_plan",
            )],
            completed_actions=[], approval_required=True, next_check_at=None,
        )

    def _normal_response(
        self,
        incident_id: str,
        triage: TriageResult,
        evidence: list[Evidence],
        medication: MedicationAssessment | None,
    ) -> CareResponse:
        unresolved = bool(medication and medication.unresolved_doses)
        confused = "new_or_worsening_confusion" in triage.red_flags
        if unresolved and confused:
            summary = "The morning medication status is unresolved and the reported change in confusion requires caregiver review."
        elif unresolved:
            summary = "The recorded medication status is unresolved and requires caregiver review."
        elif triage.incident_requires_review:
            summary = "The reported care concern requires caregiver review."
        else:
            summary = "No escalation rule matched; continue routine care coordination."

        needs_action = triage.incident_requires_review or unresolved
        actions = [self._action("Ask the primary caregiver to review the care concern.")] if needs_action else []
        return CareResponse(
            incident_id=incident_id,
            summary=summary,
            risk_level=triage.risk_level,
            evidence=evidence,
            proposed_actions=actions,
            completed_actions=[], approval_required=bool(actions), next_check_at=None,
        )

    def _fallback_response(self, incident_id: str) -> CareResponse:
        return CareResponse(
            incident_id=incident_id,
            summary="Care coordination could not be completed. Follow the household's care/emergency plan or seek appropriate human/professional help if there are urgent concerns.",
            risk_level="unknown",
            evidence=[Evidence(source="synthetic-demo", description="Care status has not been confirmed.")],
            proposed_actions=[self._action(
                "Ask the primary caregiver to review the unconfirmed care concern."
            )],
            completed_actions=[], approval_required=True, next_check_at=None,
        )
