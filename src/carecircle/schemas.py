"""Validated public MCP request and response contracts."""
from datetime import datetime, time
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

NonEmpty = Annotated[str, Field(min_length=1, pattern=r"\S")]


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class CareRequest(ContractModel):
    household_id: NonEmpty
    actor_role: NonEmpty
    utterance: NonEmpty
    session_id: NonEmpty
    incident_id: NonEmpty | None = None


class Evidence(ContractModel):
    source: NonEmpty
    description: NonEmpty


class ProposedAction(ContractModel):
    action_id: NonEmpty
    type: NonEmpty
    description: NonEmpty
    requires_confirmation: bool


class CareResponse(ContractModel):
    incident_id: NonEmpty
    summary: NonEmpty
    risk_level: Literal["low", "medium", "high", "unknown"]
    evidence: list[Evidence]
    proposed_actions: list[ProposedAction]
    completed_actions: list[str]
    approval_required: bool
    next_check_at: datetime | None
    awaiting_safety_answers: bool = False
    trace: list[dict[str, Any]] = Field(default_factory=list)


class SafetyAnswers(ContractModel):
    """Facts extracted by triage; policy decisions are made elsewhere."""

    severe_trouble_breathing: bool | None = None
    chest_pain: bool | None = None
    difficulty_speaking: bool | None = None
    awake_and_responsive: bool | None = None
    new_or_worsening_confusion: bool | None = None


class RedFlagEvaluation(ContractModel):
    has_emergency_red_flag: bool
    requires_caregiver_review: bool
    matched_rules: list[str]
    instruction: str | None


class TriageSignals(ContractModel):
    """LLM-extracted routing signals; these are not policy conclusions."""

    medication_related: bool
    safety_answers: SafetyAnswers
    safety_questions: list[str]
    evidence: list[Evidence]


class TriageResult(ContractModel):
    incident_requires_review: bool
    risk_level: Literal["low", "medium", "high", "unknown"]
    medication_related: bool
    safety_questions: list[str]
    red_flags: list[str]
    evidence: list[Evidence]
    recommended_next_step: str
    stop_normal_orchestration: bool


class MedicationRecord(ContractModel):
    id: NonEmpty
    display_name: NonEmpty
    scheduled_time: time
    inventory_count: int = Field(ge=0)


class DoseRecord(ContractModel):
    medication_id: NonEmpty
    scheduled_at: datetime
    status: Literal["taken", "missed", "unresolved"]


class MedicationAssessment(ContractModel):
    scheduled_medications: list[MedicationRecord]
    unresolved_doses: list[DoseRecord]
    inventory_notes: list[str]
    evidence: list[Evidence]


class ToolResult(ContractModel):
    """Typed internal tool envelope; values are JSON data, never model prose."""
    tool: NonEmpty
    provider: NonEmpty
    success: bool
    data: dict[str, Any]


class ActionRecord(ContractModel):
    incident_id: NonEmpty
    action_id: NonEmpty
    household_id: NonEmpty
    type: NonEmpty
    description: NonEmpty
    risk_class: Literal["READ_ONLY", "REVERSIBLE_INTERNAL", "EXTERNAL_COMMUNICATION", "DEVICE_CHANGE", "PURCHASE_OR_BOOKING", "EMERGENCY"]
    approval_required: bool
    approval_state: Literal["PENDING", "APPROVED", "REJECTED"] = "PENDING"
    execution_state: Literal["PENDING", "EXECUTING", "COMPLETED", "FAILED", "DRAFT"] = "PENDING"
    attempts: int = 0
    provider_result: dict[str, Any] | None = None
    owner: str | None = None
    next_follow_up: datetime | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class ConfirmationResult(ContractModel):
    incident_id: NonEmpty
    action_id: NonEmpty
    approval_state: NonEmpty
    execution_state: NonEmpty
    provider_result: dict[str, Any] | None
    next_check_at: datetime | None


class IncidentStatus(ContractModel):
    incident_id: NonEmpty
    household_id: NonEmpty
    status: NonEmpty
    evidence_summary: list[Evidence]
    assigned_caregiver: str | None
    completed_actions: list[ActionRecord]
    pending_actions: list[ActionRecord]
    rejected_actions: list[ActionRecord]
    next_check_at: datetime | None
    latest_event: dict[str, Any] | None
    resolution_state: NonEmpty
    medication_status: str | None = None
    home_smart_plug: str | None = None
    care_task_status: str | None = None
    draft_actions: list[ActionRecord] = Field(default_factory=list)
    next_appointment: dict[str, Any] | None = None


class HouseholdBriefing(ContractModel):
    household_id: NonEmpty
    medication_status: dict[str, Any] | None
    home_status: dict[str, Any] | None
    open_care_tasks: list[dict[str, Any]]
    next_appointment: dict[str, Any] | None
    routine_deviations: list[dict[str, Any]]
    unresolved_incidents: list[str]
    unavailable_domains: list[str]
    care_team: list[dict[str, Any]] = Field(default_factory=list)


class TraceStep(ContractModel):
    component: NonEmpty
    operation: NonEmpty
    success: bool
    latency_ms: float
    approval_state: str | None = None


class TracedCareResponse(CareResponse):
    trace: list[TraceStep] = Field(default_factory=list)
