from datetime import datetime, time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from carecircle.schemas import (
    CareRequest, CareResponse, DoseRecord, Evidence, MedicationAssessment,
    MedicationRecord, ProposedAction, TriageResult,
)


@pytest.fixture
def request_data():
    return dict(
        household_id="demo-household", actor_role="caregiver",
        utterance="Dad says he may have missed his morning medication and seems confused.",
        session_id="demo-session",
    )


@pytest.fixture
def care_request(request_data):
    return CareRequest(**request_data)


@pytest.fixture
def response():
    return CareResponse(
        incident_id="server-incident", summary="Synthetic medication status is unconfirmed.",
        risk_level="unknown",
        evidence=[Evidence(source="medication", description="Morning medication status has not been confirmed.")],
        proposed_actions=[ProposedAction(
            action_id="server-action", type="notify_primary_caregiver",
            description="Ask the caregiver to review.", requires_confirmation=True,
        )],
        completed_actions=[], approval_required=True, next_check_at=None,
    )


@pytest.fixture
def triage_result():
    return TriageResult(
        incident_requires_review=True, risk_level="high", medication_related=True,
        safety_questions=[], red_flags=["new_or_worsening_confusion"],
        evidence=[Evidence(source="triage", description="A change from normal confusion was reported.")],
        recommended_next_step="Ask a caregiver to review the reported change.",
        stop_normal_orchestration=False,
    )


@pytest.fixture
def medication_assessment():
    medication = MedicationRecord(
        id="med-heart-001", display_name="Morning heart medication",
        scheduled_time=time(8), inventory_count=4,
    )
    return MedicationAssessment(
        scheduled_medications=[medication],
        unresolved_doses=[DoseRecord(
            medication_id=medication.id,
            scheduled_at=datetime(2026, 9, 18, 8), status="unresolved",
        )],
        inventory_notes=["Morning heart medication: 4 doses remain in recorded inventory."],
        evidence=[
            Evidence(source="medication", description="The 8:00 AM medication has no recorded dose status."),
            Evidence(source="medication", description="Four doses remain in recorded inventory."),
        ],
    )


@pytest.fixture
def triage(triage_result):
    return SimpleNamespace(assess=AsyncMock(return_value=triage_result))


@pytest.fixture
def medication_agent(medication_assessment):
    return SimpleNamespace(assess=AsyncMock(return_value=medication_assessment))
