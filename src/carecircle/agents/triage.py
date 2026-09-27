"""LLM-assisted triage routing with deterministic red-flag enforcement."""
from typing import Any, Callable, Protocol

from carecircle.policy.red_flag_rules import evaluate_red_flags
from carecircle.schemas import CareRequest, Evidence, TriageResult, TriageSignals


class TriageStructuredAgent(Protocol):
    async def invoke_async(self, prompt: str, *, structured_output_model: type[TriageSignals]) -> Any: ...


class TriageAgent:
    def __init__(self, agent_factory: Callable[[], TriageStructuredAgent]):
        self._agent_factory = agent_factory

    async def assess(self, request: CareRequest) -> TriageResult:
        # Fresh Strands state prevents conversation data crossing request boundaries.
        result = await self._agent_factory().invoke_async(
            request.model_dump_json(), structured_output_model=TriageSignals
        )
        signals = TriageSignals.model_validate(result.structured_output)
        policy = evaluate_red_flags(signals.safety_answers)

        # Generated prose never crosses the specialist boundary. Evidence and safety
        # questions are rendered from typed signals using controlled language.
        evidence: list[Evidence] = []
        if signals.medication_related:
            evidence.append(Evidence(
                source="triage", description="A possible medication concern was reported."
            ))
        if signals.safety_answers.new_or_worsening_confusion:
            evidence.append(Evidence(
                source="triage", description="A new or worsening change in confusion was reported."
            ))
        for label, present in (
            ("Severe trouble breathing was reported.", signals.safety_answers.severe_trouble_breathing),
            ("Chest pain was reported.", signals.safety_answers.chest_pain),
            ("Difficulty speaking was reported.", signals.safety_answers.difficulty_speaking),
            ("The person was reported as not awake or responsive.", signals.safety_answers.awake_and_responsive is False),
        ):
            if present:
                evidence.append(Evidence(source="triage", description=label))

        safety_questions = []
        if signals.safety_answers.awake_and_responsive is None:
            safety_questions.append("Is the person awake and responsive?")

        if policy.has_emergency_red_flag:
            risk = "high"
            next_step = policy.instruction or "Follow the configured household emergency plan."
        elif policy.requires_caregiver_review:
            risk = "high"
            next_step = "Ask a caregiver to review the reported change and follow the household care plan."
        elif signals.medication_related:
            risk = "unknown"
            next_step = "Review recorded medication facts with a caregiver."
        else:
            risk = "low"
            next_step = "Continue routine care coordination."

        return TriageResult(
            incident_requires_review=policy.requires_caregiver_review or signals.medication_related,
            risk_level=risk,
            medication_related=signals.medication_related,
            safety_questions=safety_questions,
            red_flags=policy.matched_rules,
            evidence=evidence,
            recommended_next_step=next_step,
            stop_normal_orchestration=policy.has_emergency_red_flag,
        )
