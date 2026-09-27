from types import SimpleNamespace
from unittest.mock import AsyncMock

from carecircle.agents.triage import TriageAgent
from carecircle.schemas import Evidence, SafetyAnswers, TriageSignals


def llm_with(signals):
    return SimpleNamespace(
        invoke_async=AsyncMock(return_value=SimpleNamespace(structured_output=signals))
    )


async def test_standard_medication_concern(care_request):
    llm = llm_with(TriageSignals(
        medication_related=True, safety_answers=SafetyAnswers(), safety_questions=[],
        evidence=[Evidence(source="model", description="A possible missed medication was reported.")],
    ))
    result = await TriageAgent(lambda: llm).assess(care_request)
    assert result.medication_related
    assert result.risk_level == "unknown"
    assert result.evidence[0].source == "triage"


async def test_confusion_requires_review(care_request):
    llm = llm_with(TriageSignals(
        medication_related=True,
        safety_answers=SafetyAnswers(new_or_worsening_confusion=True),
        safety_questions=[], evidence=[],
    ))
    result = await TriageAgent(lambda: llm).assess(care_request)
    assert result.incident_requires_review
    assert result.risk_level == "high"
    assert not result.stop_normal_orchestration
    assert any("confusion" in item.description.lower() for item in result.evidence)


async def test_emergency_policy_stops_normal_orchestration(care_request):
    llm = llm_with(TriageSignals(
        medication_related=True,
        safety_answers=SafetyAnswers(severe_trouble_breathing=True),
        safety_questions=[], evidence=[],
    ))
    result = await TriageAgent(lambda: llm).assess(care_request)
    assert result.stop_normal_orchestration
    assert "emergency plan" in result.recommended_next_step


async def test_result_contains_no_diagnosis(care_request):
    llm = llm_with(TriageSignals(
        medication_related=True,
        safety_answers=SafetyAnswers(new_or_worsening_confusion=True),
        safety_questions=["Take two pills?"],
        evidence=[Evidence(source="model", description="Diagnosis: fabricated condition.")],
    ))
    result = await TriageAgent(lambda: llm).assess(care_request)
    rendered = result.model_dump_json().lower()
    assert "diagnosis" not in rendered
    assert "diagnose" not in rendered
    assert "two pills" not in rendered
