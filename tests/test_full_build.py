"""Offline behavior checks for the 28 private tools and four public flows."""
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from carecircle.full_supervisor import FullCareCircleSupervisor
from carecircle.internal_tools import (
    INTERNAL_TOOL_OWNERS, CareCoordinatorTools, HomeSafetyTools, LogisticsRoutineTools,
    MedicationTools, TriageTools,
)
from carecircle.providers.aws_actions import RecordingAlertProvider, RecordingSchedulerProvider, follow_up_time
from carecircle.providers.ring import SimulatedRingProvider
from carecircle.schemas import CareRequest, HouseholdBriefing, SafetyAnswers, ToolResult
from carecircle.state import InMemoryStateStore
from carecircle.workflow import ActionWorkflow, process_follow_up


@pytest.fixture
def full_stack(triage):
    store = InMemoryStateStore()
    ring = SimulatedRingProvider()
    alerts = RecordingAlertProvider()
    scheduler = RecordingSchedulerProvider()
    t = TriageTools(store)
    m = MedicationTools(store)
    h = HomeSafetyTools(store, ring)
    c = CareCoordinatorTools(store, alerts, scheduler)
    l = LogisticsRoutineTools(store)
    workflow = ActionWorkflow(store, alerts, scheduler, ring)
    supervisor = FullCareCircleSupervisor(triage, store, t, m, h, c, l, workflow)
    return SimpleNamespace(store=store, ring=ring, alerts=alerts, scheduler=scheduler, triage=t, medication=m, home=h, coordinator=c, logistics=l, workflow=workflow, supervisor=supervisor)


async def test_triage_tools_persist_answers_and_find_anomalies(full_stack):
    x = full_stack
    incident = await x.triage.create_incident("demo-household", "s1", "Concern")
    iid = incident.data["incident"]["incident_id"]
    assert x.store.get_incident(iid)["status"] == "OPEN"
    plan = await x.triage.get_emergency_plan("demo-household")
    assert "Maya" in plan.data["plan"]
    answers = await x.triage.collect_safety_answers(iid, SafetyAnswers(new_or_worsening_confusion=True))
    assert answers.data["answers"]["new_or_worsening_confusion"]
    assert "awake_and_responsive" in answers.data["remaining_questions"]
    next_turn = await x.triage.collect_safety_answers(iid, SafetyAnswers(awake_and_responsive=True))
    assert next_turn.data["answers"] == {"new_or_worsening_confusion": True, "awake_and_responsive": True}
    evaluated = await x.triage.evaluate_red_flag_rules(SafetyAnswers(severe_trouble_breathing=True))
    assert evaluated.data["evaluation"]["has_emergency_red_flag"]
    anomalies = await x.triage.get_recent_anomalies("demo-household")
    assert any(e["status"] == "unresolved" for e in anomalies.data["anomalies"])


async def test_medication_tools_persist_facts_and_draft_only(full_stack):
    x = full_stack
    iid = (await x.triage.create_incident("demo-household", "s1", "Concern")).data["incident"]["incident_id"]
    assert (await x.medication.get_medication_schedule("demo-household")).data["medications"][0]["scheduled_time"] == "08:00"
    assert (await x.medication.get_dose_history("demo-household")).data["doses"][0]["status"] == "unresolved"
    assert len((await x.medication.find_missed_doses("demo-household")).data["unresolved"]) == 1
    first = await x.medication.record_dose_status("demo-household", "med-heart-001", "taken", "dose-confirm-1")
    second = await x.medication.record_dose_status("demo-household", "med-heart-001", "taken", "dose-confirm-1")
    assert first.data["created"] and not second.data["created"]
    assert (await x.medication.get_medication_inventory("demo-household")).data["inventory"]["med-heart-001"] == 4
    refill = await x.medication.prepare_refill_request("demo-household", iid, "med-heart-001")
    assert refill.data["action"]["execution_state"] == "DRAFT"


async def test_home_tools_and_device_confirmation(full_stack):
    x = full_stack
    iid = (await x.triage.create_incident("demo-household", "s1", "Concern")).data["incident"]["incident_id"]
    assert (await x.home.get_recent_ring_events("demo-household")).data["events"][0]["time"] == "07:42"
    assert (await x.home.get_entry_activity_summary("demo-household")).data["unusual"] is True
    assert (await x.home.get_smoke_co_status("demo-household")).data["status"]["co"] == "normal"
    assert (await x.home.get_stove_or_smart_plug_status("demo-household")).data["status"]["smart_plug"] == "on"
    assert "kitchen_smart_plug_on" in (await x.home.run_home_safety_sweep("demo-household")).data["exceptions"]
    requested = await x.home.request_device_action("demo-household", iid, "stove-plug", "turn_off")
    aid = requested.data["action"]["action_id"]
    assert x.ring.executed == {}
    approved = await x.workflow.confirm("demo-household", iid, aid, True)
    assert approved.execution_state == "COMPLETED"
    assert len(x.ring.executed) == 1
    assert (await x.home.get_stove_or_smart_plug_status("demo-household")).data["status"]["smart_plug"] == "off"


async def test_coordinator_tools_sns_approval_and_follow_up(full_stack):
    x = full_stack
    iid = (await x.triage.create_incident("demo-household", "s1", "Concern")).data["incident"]["incident_id"]
    assert len((await x.coordinator.get_care_team("demo-household")).data["contacts"]) == 2
    assert (await x.coordinator.find_on_call_contact("demo-household")).data["contact"]["name"] == "John"
    alert = await x.coordinator.prepare_caregiver_alert("demo-household", iid, "Review concern")
    aid = alert.data["action"]["action_id"]
    with pytest.raises(PermissionError):
        await x.coordinator.send_approved_alert(iid, aid)
    confirmed = await x.workflow.confirm("demo-household", iid, aid, True)
    assert confirmed.execution_state == "COMPLETED"
    assert confirmed.next_check_at is not None
    assert len(x.alerts.sent) == 1
    duplicate = await x.workflow.confirm("demo-household", iid, aid, True)
    assert duplicate.execution_state == "COMPLETED" and len(x.alerts.sent) == 1
    sent = await x.coordinator.send_approved_alert(iid, aid)
    assert sent.data["duplicate"]
    assert len(x.scheduler.scheduled) == 1
    task = await x.coordinator.update_care_task("demo-household", "morning-check", "ACKNOWLEDGED")
    assert task.data["task"]["status"] == "ACKNOWLEDGED"
    for state in ("OPEN", "ASSIGNED", "IN_PROGRESS", "COMPLETED", "DECLINED", "BLOCKED"):
        assert (await x.coordinator.update_care_task("demo-household", "morning-check", state)).data["task"]["status"] == state
    assert (await x.coordinator.schedule_follow_up_check("demo-household", iid, datetime.now(timezone.utc))).data["schedule"]["provider"]


def test_demo_follow_up_waits_beyond_interactive_rehearsal():
    started = datetime.now(timezone.utc)
    demo_delay = follow_up_time(True) - started
    production_delay = follow_up_time(False) - started
    assert 299 <= demo_delay.total_seconds() <= 301
    assert 1799 <= production_delay.total_seconds() <= 1801


async def test_rejection_never_sends_and_logistics_drafts(full_stack):
    x = full_stack
    iid = (await x.triage.create_incident("demo-household", "s1", "Concern")).data["incident"]["incident_id"]
    aid = (await x.coordinator.prepare_caregiver_alert("demo-household", iid, "Review concern")).data["action"]["action_id"]
    rejected = await x.workflow.confirm("demo-household", iid, aid, False)
    assert rejected.approval_state == "REJECTED" and not x.alerts.sent
    assert (await x.logistics.get_upcoming_appointments("demo-household")).data["appointments"][0]["time"] == "14:30"
    assert len((await x.logistics.get_daily_routine("demo-household")).data["routine"]) == 3
    assert (await x.logistics.get_pharmacy_details("demo-household")).data["pharmacy"]["name"] == "Demo Pharmacy"
    ride = await x.logistics.prepare_ride_request("demo-household", iid, "cardiology")
    supply = await x.logistics.prepare_supply_request("demo-household", iid, "gloves")
    for action in (ride.data["action"], supply.data["action"]):
        assert action["execution_state"] == "DRAFT"
        after = await x.workflow.confirm("demo-household", iid, action["action_id"], True)
        assert after.execution_state == "DRAFT"


async def test_supervisor_briefing_status_and_bounded_follow_up(full_stack, care_request):
    x = full_stack
    briefing = await x.supervisor.briefing("demo-household")
    assert isinstance(briefing, HouseholdBriefing)
    assert briefing.medication_status["unresolved"]
    assert briefing.next_appointment["time"] == "14:30"
    response = await x.supervisor.coordinate(care_request)
    assert response.approval_required
    assert {item["component"] for item in response.trace} >= {"Triage Agent", "Safety Policy", "Medication Agent", "Home Safety Agent", "Care Coordinator Agent", "DynamoDB"}
    iid = response.incident_id
    status = x.workflow.status("demo-household", iid)
    assert status.status == "OPEN" and status.pending_actions
    assert (await x.workflow.confirm("demo-household", iid, response.proposed_actions[0].action_id, True)).next_check_at
    assert process_follow_up(x.store, "demo-household", iid)["state"] == "FOLLOW_UP_DUE"
    assert x.workflow.status("demo-household", iid).latest_event["kind"] == "follow_up"
    assert any(a.action_id == "follow-up-escalation" for a in x.workflow.status("demo-household", iid).pending_actions)
    assert process_follow_up(x.store, "demo-household", iid)["state"] == "FOLLOW_UP_DUE"


async def test_resolved_incident_closes_follow_up(full_stack):
    x = full_stack
    iid = (await x.triage.create_incident("demo-household", "s1", "Concern")).data["incident"]["incident_id"]
    incident = x.store.get_incident(iid)
    incident["resolution_state"] = "RESOLVED"
    x.store.update_incident(iid, incident)
    assert process_follow_up(x.store, "demo-household", iid)["state"] == "CLOSED"
    assert not any(e.get("kind") == "follow_up" for e in x.store.list_events("demo-household"))


async def test_resolution_supersedes_pending_follow_up_escalation(full_stack):
    x = full_stack
    iid = (await x.triage.create_incident("demo-household", "voice-resolution", "Concern")).data["incident"]["incident_id"]
    assert process_follow_up(x.store, "demo-household", iid)["state"] == "FOLLOW_UP_DUE"
    assert x.store.get_action(iid, "follow-up-escalation")["approval_state"] == "PENDING"

    await x.supervisor.coordinate(CareRequest(
        household_id="demo-household", actor_role="caregiver", session_id="voice-resolution",
        incident_id=iid,
        utterance="John checked on Dad. Dad is okay and confirmed he already took his morning medication.",
    ))

    action = x.store.get_action(iid, "follow-up-escalation")
    status = x.workflow.status("demo-household", iid)
    assert status.status == status.resolution_state == "RESOLVED"
    assert status.medication_status == "taken" and status.care_task_status == "COMPLETED"
    assert action["approval_state"] == "REJECTED"
    assert action["execution_state"] == "PENDING"
    assert action["provider_result"] == {"status": "superseded", "reason": "incident_resolved"}
    assert not status.pending_actions
    assert any(item.action_id == "follow-up-escalation" for item in status.rejected_actions)


async def test_briefing_partial_failure_and_unknown_household(full_stack):
    x = full_stack
    x.supervisor.home.assess = AsyncMock(side_effect=RuntimeError("private provider failure"))
    briefing = await x.supervisor.briefing("demo-household")
    assert briefing.home_status is None and "home" in briefing.unavailable_domains
    with pytest.raises(KeyError):
        await x.supervisor.briefing("unknown")


async def test_full_supervisor_emergency_short_circuit(full_stack, triage_result, care_request):
    x = full_stack
    triage_result.stop_normal_orchestration = True
    triage_result.red_flags = ["not_awake_or_responsive"]
    x.supervisor.triage_agent.assess = AsyncMock(return_value=triage_result)
    x.supervisor.home.assess = AsyncMock(side_effect=AssertionError("home must not run"))
    response = await x.supervisor.coordinate(care_request)
    assert response.risk_level == "high"
    assert "emergency plan" in response.summary
    assert all(step["component"] != "Home Safety Agent" for step in response.trace)


async def test_full_supervisor_model_failure_persists_safe_fallback(full_stack, care_request):
    x = full_stack
    x.supervisor.triage_agent.assess = AsyncMock(side_effect=RuntimeError("private prompt"))
    response = await x.supervisor.coordinate(care_request)
    assert response.risk_level == "unknown" and response.approval_required
    assert x.store.get_incident(response.incident_id)


def test_exact_internal_tool_inventory():
    assert len(INTERNAL_TOOL_OWNERS) == 28
    for name, owner in INTERNAL_TOOL_OWNERS.items():
        assert callable(getattr(owner, name))
