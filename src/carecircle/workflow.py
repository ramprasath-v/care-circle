"""Deterministic approval, incident status, and bounded follow-up workflow."""
from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

from carecircle.providers.aws_actions import AlertProvider, SchedulerProvider, follow_up_time
from carecircle.providers.ring import RingProvider
from carecircle.progress import emit
from carecircle.schemas import ActionRecord, ConfirmationResult, Evidence, IncidentStatus
from carecircle.state import StateStore, now_iso


def create_action(store: StateStore, household_id: str, incident_id: str, action_type: str, description: str, risk_class: str, *, owner: str | None = None, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    incident = store.get_incident(incident_id)
    if not incident or incident["household_id"] != household_id:
        raise KeyError("UnknownIncident")
    action = ActionRecord(incident_id=incident_id, action_id=str(uuid4()), household_id=household_id, type=action_type, description=description, risk_class=risk_class, approval_required=risk_class in {"EXTERNAL_COMMUNICATION", "DEVICE_CHANGE", "PURCHASE_OR_BOOKING", "EMERGENCY"}, execution_state="DRAFT" if risk_class == "PURCHASE_OR_BOOKING" else "PENDING", owner=owner).model_dump(mode="json")
    action["payload"] = payload or {}
    store.put_action(incident_id, action["action_id"], action)
    return action


def policy_decision(risk_class: str, approved: bool) -> str:
    if not approved:
        return "REJECTED"
    return {
        "READ_ONLY": "EXECUTE", "REVERSIBLE_INTERNAL": "EXECUTE",
        "EXTERNAL_COMMUNICATION": "EXECUTE", "DEVICE_CHANGE": "EXECUTE",
        "PURCHASE_OR_BOOKING": "DRAFT_ONLY", "EMERGENCY": "HUMAN_PLAN_ONLY",
    }[risk_class]


class ActionWorkflow:
    def __init__(self, store: StateStore, alerts: AlertProvider, scheduler: SchedulerProvider, ring: RingProvider, *, demo_mode: bool = True):
        self.store, self.alerts, self.scheduler, self.ring = store, alerts, scheduler, ring
        self.demo_mode = demo_mode
        self.coordinator_tools = None

    async def confirm(self, household_id: str, incident_id: str, action_id: str, approved: bool) -> ConfirmationResult:
        emit("Safety Policy", "confirm_action", "RUNNING")
        incident = self.store.get_incident(incident_id)
        action = self.store.get_action(incident_id, action_id)
        if not incident or not action or incident["household_id"] != household_id or action["household_id"] != household_id:
            raise KeyError("UnknownAction")
        if action["approval_state"] != "PENDING":
            if action["type"] == "caregiver_alert" and action["execution_state"] == "COMPLETED" and not incident.get("next_check_at"):
                when = follow_up_time(self.demo_mode)
                emit("EventBridge Scheduler", "schedule_follow_up_check", "RUNNING")
                try:
                    schedule = (await self.coordinator_tools.schedule_follow_up_check(household_id, incident_id, when)).data["schedule"] if self.coordinator_tools else self.scheduler.schedule(incident_id, household_id, when)
                except Exception:
                    emit("EventBridge Scheduler", "schedule_follow_up_check", "FAILED", provider="EventBridgeScheduler")
                    raise
                emit("EventBridge Scheduler", "schedule_follow_up_check", "COMPLETE", provider="EventBridgeScheduler")
                incident["next_check_at"] = when.isoformat()
                incident["assigned_caregiver"] = action.get("owner")
                incident["follow_up_schedule"] = schedule
                self.store.update_incident(incident_id, incident)
            emit("Safety Policy", "confirm_action", "COMPLETE")
            return self._confirmation(action, incident)
        decision = policy_decision(action["risk_class"], approved)
        if decision == "REJECTED":
            action["approval_state"] = "REJECTED"
            action["execution_state"] = "DRAFT" if action["risk_class"] == "PURCHASE_OR_BOOKING" else "PENDING"
            self.store.update_action(incident_id, action_id, action)
            emit("Safety Policy", "confirm_action", "COMPLETE")
            return self._confirmation(action, incident)
        action["approval_state"] = "APPROVED"
        self.store.update_action(incident_id, action_id, action)
        emit("Safety Policy", "confirm_action", "COMPLETE")
        if decision in {"DRAFT_ONLY", "HUMAN_PLAN_ONLY"}:
            action["execution_state"] = "DRAFT" if decision == "DRAFT_ONLY" else "COMPLETED"
            action["provider_result"] = {"status": "approved_draft" if decision == "DRAFT_ONLY" else "human_plan_instructions_only"}
        elif action["type"] == "caregiver_alert":
            if not self.coordinator_tools and not self.store.claim_action(incident_id, action_id):
                raise RuntimeError("ActionAlreadyClaimed")
            try:
                emit("SNS", "send_approved_alert", "RUNNING")
                if self.coordinator_tools:
                    action["provider_result"] = (await self.coordinator_tools.send_approved_alert(incident_id, action_id)).data["provider_result"]
                else:
                    action["provider_result"] = self.alerts.send(action_id, action["payload"]["message"], incident_id, household_id, action.get("owner") or "maya")
                emit("SNS", "send_approved_alert", "COMPLETE", provider="SNS")
            except Exception:
                emit("SNS", "send_approved_alert", "FAILED", provider="SNS")
                action["execution_state"] = "FAILED"
                self.store.update_action(incident_id, action_id, action)
                raise
            action["execution_state"] = "COMPLETED"
            action["attempts"] += 1
            self.store.update_action(incident_id, action_id, action)
            when = follow_up_time(self.demo_mode)
            emit("EventBridge Scheduler", "schedule_follow_up_check", "RUNNING")
            try:
                schedule = (await self.coordinator_tools.schedule_follow_up_check(household_id, incident_id, when)).data["schedule"] if self.coordinator_tools else self.scheduler.schedule(incident_id, household_id, when)
            except Exception:
                emit("EventBridge Scheduler", "schedule_follow_up_check", "FAILED", provider="EventBridgeScheduler")
                raise
            emit("EventBridge Scheduler", "schedule_follow_up_check", "COMPLETE", provider="EventBridgeScheduler")
            incident["next_check_at"] = when.isoformat()
            incident["assigned_caregiver"] = action.get("owner")
            incident["follow_up_schedule"] = schedule
            self.store.update_incident(incident_id, incident)
        elif action["type"] == "device_change":
            if not self.store.claim_action(incident_id, action_id):
                raise RuntimeError("ActionAlreadyClaimed")
            payload = action["payload"]
            action["provider_result"] = await self.ring.execute_device_action(household_id, payload["device_id"], payload["command"])
            action["execution_state"] = "COMPLETED"
            action["attempts"] += 1
        else:
            action["execution_state"] = "COMPLETED"
            action["provider_result"] = {"status": "internal_complete"}
        self.store.update_action(incident_id, action_id, action)
        return self._confirmation(action, incident)

    @staticmethod
    def _confirmation(action: dict[str, Any], incident: dict[str, Any]) -> ConfirmationResult:
        next_check = incident.get("next_check_at")
        return ConfirmationResult(incident_id=action["incident_id"], action_id=action["action_id"], approval_state=action["approval_state"], execution_state=action["execution_state"], provider_result=action.get("provider_result"), next_check_at=datetime.fromisoformat(next_check) if next_check else None)

    def status(self, household_id: str, incident_id: str) -> IncidentStatus:
        incident = self.store.get_incident(incident_id)
        if not incident or incident["household_id"] != household_id:
            raise KeyError("UnknownIncident")
        actions = [ActionRecord.model_validate(x) for x in self.store.list_actions(incident_id)]
        events = [x for x in self.store.list_events(household_id) if x.get("incident_id") == incident_id]
        profile = self.store.get_profile(household_id) or {}
        doses = [x for x in events if x.get("kind") == "dose_status" and x.get("medication_id") == "med-heart-001"]
        devices = profile.get("devices", [])
        tasks = profile.get("care_tasks", [])
        return IncidentStatus(
            incident_id=incident_id, household_id=household_id, status=incident["status"],
            evidence_summary=[Evidence.model_validate(x) for x in incident.get("evidence", [])],
            assigned_caregiver=incident.get("assigned_caregiver"),
            completed_actions=[x for x in actions if x.execution_state == "COMPLETED"],
            pending_actions=[x for x in actions if x.approval_state == "PENDING" or x.execution_state in {"EXECUTING", "DRAFT"} and x.approval_state != "REJECTED"],
            rejected_actions=[x for x in actions if x.approval_state == "REJECTED"],
            next_check_at=datetime.fromisoformat(incident["next_check_at"]) if incident.get("next_check_at") else None, latest_event=events[0] if events else None,
            resolution_state=incident["resolution_state"],
            medication_status=doses[0]["status"] if doses else "unresolved" if household_id == "demo-household" else None,
            home_smart_plug=next((x.get("state", "on") for x in devices if x["id"] == "stove-plug"), None),
            care_task_status=incident.get("care_task_status", "OPEN" if household_id == "demo-household" else next((x["status"] for x in tasks if x["id"] == "morning-check"), None)),
            draft_actions=[x for x in actions if x.execution_state == "DRAFT"],
            next_appointment=next(iter(profile.get("appointments", [])), None),
        )


def process_follow_up(store: StateStore, household_id: str, incident_id: str) -> dict[str, Any]:
    incident = store.get_incident(incident_id)
    if not incident or incident["household_id"] != household_id:
        raise KeyError("UnknownIncident")
    if incident["resolution_state"] == "RESOLVED":
        incident["next_check_at"] = None
        store.update_incident(incident_id, incident)
        return {"state": "CLOSED", "incident_id": incident_id}
    if incident.get("status") == "FOLLOW_UP_DUE" and not incident.get("next_check_at"):
        return {"state": "FOLLOW_UP_DUE", "incident_id": incident_id}
    event_id = f"follow-up-{incident_id}"
    event = {"event_id": event_id, "incident_id": incident_id, "kind": "follow_up", "status": "needs_caregiver_check", "timestamp": now_iso()}
    store.put_event(household_id, event_id, event)
    incident["status"] = "FOLLOW_UP_DUE"
    incident["next_check_at"] = None
    incident["care_task_status"] = "ASSIGNED"
    store.update_incident(incident_id, incident)
    profile = store.get_profile(household_id)
    if profile:
        for task in profile.get("care_tasks", []):
            if task["status"] == "OPEN":
                task["status"] = "ASSIGNED"
        store.put_profile(household_id, profile)
    escalation_id = "follow-up-escalation"
    escalation = ActionRecord(incident_id=incident_id, action_id=escalation_id, household_id=household_id, type="caregiver_alert", description="Ask backup caregiver John to review the unresolved incident.", risk_class="EXTERNAL_COMMUNICATION", approval_required=True, owner="john", payload={"message": f"CareCircle: please review unresolved incident {incident_id}."}).model_dump(mode="json")
    store.put_action(incident_id, escalation_id, escalation)
    return {"state": "FOLLOW_UP_DUE", "incident_id": incident_id}
