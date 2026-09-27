import asyncio
import logging
from uuid import UUID

from carecircle.schemas import CareResponse
from carecircle.supervisor import CareCircleSupervisor


async def test_calls_specialists_and_merges_evidence(
    triage, medication_agent, care_request
):
    result = await CareCircleSupervisor(triage, medication_agent).coordinate(care_request)
    assert isinstance(result, CareResponse)
    UUID(result.incident_id)
    UUID(result.proposed_actions[0].action_id)
    triage.assess.assert_awaited_once_with(care_request)
    medication_agent.assess.assert_awaited_once_with("demo-household")
    assert [item.source for item in result.evidence] == ["triage", "medication", "medication"]
    assert "confusion" in result.summary
    assert result.approval_required


async def test_emergency_stops_medication(
    triage, triage_result, medication_agent, care_request
):
    triage_result.stop_normal_orchestration = True
    triage_result.recommended_next_step = "Follow the configured household emergency plan."
    result = await CareCircleSupervisor(triage, medication_agent).coordinate(care_request)
    medication_agent.assess.assert_not_awaited()
    assert result.risk_level == "high"
    assert "emergency plan" in result.summary


async def test_triage_failure_returns_safe_fallback(
    triage, medication_agent, care_request
):
    triage.assess.side_effect = RuntimeError("private model output")
    result = await CareCircleSupervisor(triage, medication_agent).coordinate(care_request)
    assert result.risk_level == "unknown"
    assert result.completed_actions == []
    assert "care/emergency plan" in result.summary
    medication_agent.assess.assert_not_awaited()


async def test_medication_failure_returns_safe_fallback(
    triage, medication_agent, care_request
):
    medication_agent.assess.side_effect = RuntimeError("provider unavailable")
    result = await CareCircleSupervisor(triage, medication_agent).coordinate(care_request)
    assert result.risk_level == "unknown"
    assert result.approval_required


async def test_timeout(triage, medication_agent, care_request):
    async def slow(*args, **kwargs):
        await asyncio.sleep(10)
    triage.assess.side_effect = slow
    result = await CareCircleSupervisor(triage, medication_agent, 0.01).coordinate(care_request)
    assert result.risk_level == "unknown"


async def test_private_structured_logs(
    triage, medication_agent, care_request, caplog
):
    with caplog.at_level(logging.INFO, logger="carecircle"):
        await CareCircleSupervisor(triage, medication_agent).coordinate(care_request)
    assert care_request.utterance not in caplog.text
    assert '"selected_specialists": ["triage", "medication"]' in caplog.text
    assert '"specialist_latency_ms"' in caplog.text
    assert '"policy_outcome": "caregiver_review"' in caplog.text
    assert '"incident_id"' in caplog.text
