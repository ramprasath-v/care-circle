"""The exact 28 private, provider-backed specialist tools."""
from __future__ import annotations

from datetime import datetime
from functools import wraps
from time import perf_counter
from typing import Any
from uuid import uuid4

from carecircle.policy.red_flag_rules import evaluate_red_flags
from carecircle.progress import elapsed_ms, emit
from carecircle.providers.aws_actions import AlertProvider, SchedulerProvider
from carecircle.providers.ring import RingProvider
from carecircle.schemas import SafetyAnswers, ToolResult
from carecircle.state import StateStore, is_current_demo_event, now_iso


def result(tool: str, provider: str, **data: Any) -> ToolResult:
    return ToolResult(tool=tool, provider=provider, success=True, data=data)


class ToolBase:
    def __init__(self, store: StateStore):
        self.store = store

    def profile(self, household_id: str) -> dict[str, Any]:
        profile = self.store.get_profile(household_id)
        if profile is None:
            raise KeyError("UnknownHousehold")
        return profile


class TriageTools(ToolBase):
    async def create_incident(self, household_id: str, session_id: str, summary: str, risk_level: str = "unknown") -> ToolResult:
        self.profile(household_id)
        incident_id = str(uuid4())
        incident = {"incident_id": incident_id, "household_id": household_id, "session_id": session_id, "status": "OPEN", "resolution_state": "UNRESOLVED", "summary": summary, "risk_level": risk_level, "evidence": [], "assigned_caregiver": None, "next_check_at": None, "safety_answers": {}, "created_at": now_iso()}
        if not self.store.put_incident(incident_id, incident):
            raise RuntimeError("IncidentCollision")
        return result("create_incident", "ActionLedger", incident=incident)

    async def get_emergency_plan(self, household_id: str) -> ToolResult:
        return result("get_emergency_plan", "CareProfiles", plan=self.profile(household_id)["emergency_plan"])

    async def collect_safety_answers(self, incident_id: str, answers: SafetyAnswers) -> ToolResult:
        incident = self.store.get_incident(incident_id)
        if not incident:
            raise KeyError("UnknownIncident")
        merged = {**incident.get("safety_answers", {}), **answers.model_dump(exclude_none=True)}
        incident["safety_answers"] = merged
        self.store.update_incident(incident_id, incident)
        remaining = [name for name in SafetyAnswers.model_fields if name not in merged]
        return result("collect_safety_answers", "ActionLedger", answers=merged, remaining_questions=remaining)

    async def evaluate_red_flag_rules(self, answers: SafetyAnswers) -> ToolResult:
        evaluation = evaluate_red_flags(answers)
        return result("evaluate_red_flag_rules", "deterministic-policy", evaluation=evaluation.model_dump())

    async def get_recent_anomalies(self, household_id: str) -> ToolResult:
        profile = self.profile(household_id)
        anomalies = [x for x in self.store.list_events(household_id)
                     if (household_id != "demo-household" or x.get("event_id") == "routine-walk" or is_current_demo_event(profile, x))
                     and (x.get("kind") in {"routine_exception", "check_in_exception", "home_exception"}
                          or (x.get("kind") == "dose_status" and x.get("status") != "taken"))]
        return result("get_recent_anomalies", "CareEvents", anomalies=anomalies)


class MedicationTools(ToolBase):
    async def get_medication_schedule(self, household_id: str) -> ToolResult:
        return result("get_medication_schedule", "CareProfiles", medications=self.profile(household_id)["medications"])

    async def get_dose_history(self, household_id: str) -> ToolResult:
        profile = self.profile(household_id)
        return result("get_dose_history", "CareEvents", doses=[x for x in self.store.list_events(household_id)
            if x.get("kind") == "dose_status" and (household_id != "demo-household" or is_current_demo_event(profile, x))])

    async def find_missed_doses(self, household_id: str) -> ToolResult:
        schedule = (await self.get_medication_schedule(household_id)).data["medications"]
        history = (await self.get_dose_history(household_id)).data["doses"]
        latest = {x["medication_id"]: x for x in reversed(history)}
        unresolved = [x for x in schedule if latest.get(x["id"], {}).get("status", "unresolved") in {"unresolved", "missed"}]
        return result("find_missed_doses", "deterministic-comparison", unresolved=unresolved)

    async def record_dose_status(self, household_id: str, medication_id: str, status: str, event_id: str, incident_id: str | None = None) -> ToolResult:
        if status not in {"taken", "missed", "unresolved"}:
            raise ValueError("InvalidDoseStatus")
        schedule = (await self.get_medication_schedule(household_id)).data["medications"]
        if medication_id not in {x["id"] for x in schedule}:
            raise KeyError("UnknownMedication")
        event = {"event_id": event_id, "kind": "dose_status", "medication_id": medication_id, "status": status, "timestamp": now_iso()}
        if incident_id:
            event["incident_id"] = incident_id
        created = self.store.put_event(household_id, event_id, event)
        return result("record_dose_status", "CareEvents", event=event, created=created)

    async def get_medication_inventory(self, household_id: str) -> ToolResult:
        meds = (await self.get_medication_schedule(household_id)).data["medications"]
        return result("get_medication_inventory", "CareProfiles", inventory={x["id"]: x["inventory_count"] for x in meds})

    async def prepare_refill_request(self, household_id: str, incident_id: str, medication_id: str) -> ToolResult:
        self.profile(household_id)
        from carecircle.workflow import create_action
        action = create_action(self.store, household_id, incident_id, "refill_draft", f"Draft refill request for {medication_id}.", "PURCHASE_OR_BOOKING")
        return result("prepare_refill_request", "ActionLedger", action=action)


class HomeSafetyTools(ToolBase):
    def __init__(self, store: StateStore, ring: RingProvider):
        super().__init__(store)
        self.ring = ring

    async def get_recent_ring_events(self, household_id: str) -> ToolResult:
        self.profile(household_id)
        return result("get_recent_ring_events", "simulated-ring", events=await self.ring.recent_events(household_id))

    async def get_entry_activity_summary(self, household_id: str) -> ToolResult:
        events = (await self.get_recent_ring_events(household_id)).data["events"]
        return result("get_entry_activity_summary", "simulated-ring", summary="Front door opened at 7:42 AM; expected walk activity has not been observed." if events else "No recent entry data.", unusual=True if events else None)

    async def get_smoke_co_status(self, household_id: str) -> ToolResult:
        self.profile(household_id)
        return result("get_smoke_co_status", "simulated-ring", status=await self.ring.smoke_co_status(household_id))

    async def get_stove_or_smart_plug_status(self, household_id: str) -> ToolResult:
        self.profile(household_id)
        return result("get_stove_or_smart_plug_status", "simulated-ring", status=await self.ring.stove_status(household_id))

    async def run_home_safety_sweep(self, household_id: str) -> ToolResult:
        entry = await self.get_entry_activity_summary(household_id)
        smoke = await self.get_smoke_co_status(household_id)
        stove = await self.get_stove_or_smart_plug_status(household_id)
        exceptions = ["expected_walk_not_observed"] if entry.data["unusual"] else []
        if stove.data["status"].get("smart_plug") == "on":
            exceptions.append("kitchen_smart_plug_on")
        return result("run_home_safety_sweep", "simulated-ring", entry=entry.data, smoke_co=smoke.data, stove=stove.data, exceptions=exceptions)

    async def request_device_action(self, household_id: str, incident_id: str, device_id: str, command: str) -> ToolResult:
        self.profile(household_id)
        from carecircle.workflow import create_action
        action = create_action(self.store, household_id, incident_id, "device_change", f"Simulated {command} for {device_id}.", "DEVICE_CHANGE", payload={"device_id": device_id, "command": command})
        return result("request_device_action", "ActionLedger", action=action)


TASK_STATES = {"OPEN", "ASSIGNED", "ACKNOWLEDGED", "IN_PROGRESS", "COMPLETED", "DECLINED", "BLOCKED"}


class CareCoordinatorTools(ToolBase):
    def __init__(self, store: StateStore, alerts: AlertProvider, scheduler: SchedulerProvider):
        super().__init__(store)
        self.alerts = alerts
        self.scheduler = scheduler

    async def get_care_team(self, household_id: str) -> ToolResult:
        return result("get_care_team", "CareProfiles", contacts=self.profile(household_id)["care_team"])

    async def find_on_call_contact(self, household_id: str) -> ToolResult:
        team = (await self.get_care_team(household_id)).data["contacts"]
        contact = next((x for x in team if x["on_call"]), team[0] if team else None)
        return result("find_on_call_contact", "CareProfiles", contact=contact)

    async def prepare_caregiver_alert(self, household_id: str, incident_id: str, summary: str) -> ToolResult:
        contact = (await self.find_on_call_contact(household_id)).data["contact"]
        from carecircle.workflow import create_action
        action = create_action(self.store, household_id, incident_id, "caregiver_alert", f"Alert {contact['name']} to review the care concern.", "EXTERNAL_COMMUNICATION", owner=contact["id"], payload={"message": f"CareCircle: please review incident {incident_id}. {summary}"})
        return result("prepare_caregiver_alert", "ActionLedger", action=action, contact=contact)

    async def send_approved_alert(self, incident_id: str, action_id: str) -> ToolResult:
        action = self.store.get_action(incident_id, action_id)
        if not action or action["type"] != "caregiver_alert" or action["approval_state"] != "APPROVED":
            raise PermissionError("AlertRequiresApproval")
        if action["execution_state"] == "COMPLETED":
            return result("send_approved_alert", "SNS", provider_result=action["provider_result"], duplicate=True)
        if not self.store.claim_action(incident_id, action_id):
            raise RuntimeError("ActionAlreadyClaimed")
        provider_result = self.alerts.send(action_id, action["payload"]["message"], incident_id, action["household_id"], action.get("owner") or "maya")
        action["execution_state"] = "COMPLETED"
        action["attempts"] = action.get("attempts", 0) + 1
        action["provider_result"] = provider_result
        self.store.update_action(incident_id, action_id, action)
        return result("send_approved_alert", "SNS", provider_result=provider_result, duplicate=False)

    async def schedule_follow_up_check(self, household_id: str, incident_id: str, when: datetime) -> ToolResult:
        incident = self.store.get_incident(incident_id)
        if not incident or incident["household_id"] != household_id:
            raise KeyError("UnknownIncident")
        provider_result = self.scheduler.schedule(incident_id, household_id, when)
        incident["next_check_at"] = when.isoformat()
        self.store.update_incident(incident_id, incident)
        return result("schedule_follow_up_check", "EventBridgeScheduler", schedule=provider_result)

    async def update_care_task(self, household_id: str, task_id: str, status: str) -> ToolResult:
        if status not in TASK_STATES:
            raise ValueError("InvalidCareTaskState")
        profile = self.profile(household_id)
        task = next((x for x in profile["care_tasks"] if x["id"] == task_id), None)
        if not task:
            raise KeyError("UnknownCareTask")
        task["status"] = status
        if status == "ASSIGNED" and not task.get("owner"):
            task["owner"] = next((x["id"] for x in profile.get("care_team", []) if x.get("on_call")), None)
        self.store.put_profile(household_id, profile)
        return result("update_care_task", "CareProfiles", task=task)


class LogisticsRoutineTools(ToolBase):
    async def get_upcoming_appointments(self, household_id: str) -> ToolResult:
        return result("get_upcoming_appointments", "CareProfiles", appointments=self.profile(household_id)["appointments"])

    async def get_daily_routine(self, household_id: str) -> ToolResult:
        return result("get_daily_routine", "CareProfiles", routine=self.profile(household_id)["routine"])

    async def get_pharmacy_details(self, household_id: str) -> ToolResult:
        return result("get_pharmacy_details", "CareProfiles", pharmacy=self.profile(household_id)["pharmacy"])

    async def prepare_ride_request(self, household_id: str, incident_id: str, appointment_id: str) -> ToolResult:
        self.profile(household_id)
        from carecircle.workflow import create_action
        action = create_action(self.store, household_id, incident_id, "ride_draft", f"Draft ride for appointment {appointment_id}.", "PURCHASE_OR_BOOKING")
        return result("prepare_ride_request", "ActionLedger", action=action)

    async def prepare_supply_request(self, household_id: str, incident_id: str, supply: str) -> ToolResult:
        self.profile(household_id)
        from carecircle.workflow import create_action
        action = create_action(self.store, household_id, incident_id, "supply_draft", f"Draft supply request for {supply}.", "PURCHASE_OR_BOOKING")
        return result("prepare_supply_request", "ActionLedger", action=action)


INTERNAL_TOOL_OWNERS: dict[str, type[ToolBase]] = {
    **{name: TriageTools for name in ("create_incident", "get_emergency_plan", "collect_safety_answers", "evaluate_red_flag_rules", "get_recent_anomalies")},
    **{name: MedicationTools for name in ("get_medication_schedule", "get_dose_history", "find_missed_doses", "record_dose_status", "get_medication_inventory", "prepare_refill_request")},
    **{name: HomeSafetyTools for name in ("get_recent_ring_events", "get_entry_activity_summary", "get_smoke_co_status", "get_stove_or_smart_plug_status", "run_home_safety_sweep", "request_device_action")},
    **{name: CareCoordinatorTools for name in ("get_care_team", "find_on_call_contact", "prepare_caregiver_alert", "send_approved_alert", "schedule_follow_up_check", "update_care_task")},
    **{name: LogisticsRoutineTools for name in ("get_upcoming_appointments", "get_daily_routine", "get_pharmacy_details", "prepare_ride_request", "prepare_supply_request")},
}


_COMPONENTS = {
    TriageTools: "Triage Agent", MedicationTools: "Medication Agent",
    HomeSafetyTools: "Home Safety Agent", CareCoordinatorTools: "Care Coordinator Agent",
    LogisticsRoutineTools: "Logistics & Routine Agent",
}


def _instrument_tool(name: str, owner: type[ToolBase]) -> None:
    original = getattr(owner, name)

    @wraps(original)
    async def traced(self, *args, **kwargs):
        component = _COMPONENTS[owner]
        started = perf_counter()
        emit(component, name, "RUNNING", kind="tool")
        try:
            value = await original(self, *args, **kwargs)
        except BaseException:
            emit(component, name, "FAILED", latency_ms=elapsed_ms(started), kind="tool")
            raise
        emit(component, name, "COMPLETE", provider=value.provider, latency_ms=elapsed_ms(started), kind="tool")
        return value

    setattr(owner, name, traced)


for _name, _owner in INTERNAL_TOOL_OWNERS.items():
    _instrument_tool(_name, _owner)
