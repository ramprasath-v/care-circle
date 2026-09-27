"""Six-agent, deterministic routing around the existing Strands triage specialist."""
from __future__ import annotations

import asyncio
import re
from time import perf_counter
from typing import Any

from carecircle.internal_tools import CareCoordinatorTools, HomeSafetyTools, LogisticsRoutineTools, MedicationTools, TriageTools
from carecircle.progress import emit
from carecircle.schemas import CareRequest, CareResponse, Evidence, HouseholdBriefing, ProposedAction, SafetyAnswers
from carecircle.state import StateStore, is_current_demo_event
from carecircle.supervisor import TriageSpecialist, log_event
from carecircle.workflow import ActionWorkflow, supersede_follow_up_escalation


AGENT_NAMES = (
    "CareCircle Supervisor", "Triage Agent", "Medication Agent", "Home Safety Agent",
    "Care Coordinator Agent", "Logistics & Routine Agent",
)
REQUIRED_SAFETY_FIELDS = ("awake_and_responsive", "chest_pain", "severe_trouble_breathing", "difficulty_speaking")
SAFETY_QUESTIONS = {
    "awake_and_responsive": "Is Dad awake and responsive?",
    "chest_pain": "Does Dad have chest pain?",
    "severe_trouble_breathing": "Does Dad have trouble breathing?",
    "difficulty_speaking": "Does Dad have trouble speaking?",
}


def _missing_safety_question(answers: SafetyAnswers) -> str:
    missing = [SAFETY_QUESTIONS[name] for name in REQUIRED_SAFETY_FIELDS if getattr(answers, name) is None]
    return " ".join(missing)


def _continuation_intent(utterance: str) -> str | None:
    """Only explicit demo facts route to mutating private tools."""
    text = utterance.casefold()
    if ("smart plug" in text or "kitchen plug" in text) and re.search(r"\b(turn off|switch off)\b", text):
        return "device"
    if "already took" in text and "medication" in text and ("john checked" in text or "confirmed" in text):
        return "resolution"
    if "rest of" in text and "day" in text or "appointment and medication supplies" in text:
        return "drafts"
    if any(phrase in text for phrase in ("awake and responsive", "not awake", "unresponsive", "chest pain", "breathing trouble", "trouble breathing", "breathing problems", "difficulty breathing", "difficulty speaking", "trouble speaking")):
        return "safety_answers"
    return None


def _spoken_safety_answers(utterance: str) -> SafetyAnswers:
    """Parse only explicit answers; unclear answers stay unknown for the policy."""
    text = utterance.casefold().replace("’", "'")
    no_chest = bool(re.search(r"\b(?:no|without) chest pain\b", text))
    breathing = r"(?:breathing trouble|trouble breathing|difficulty breathing|breathing problems?)"
    speaking = r"(?:(?:difficulty|trouble) speaking|speech problems?)"
    no_breathing = bool(re.search(rf"\b(?:no|without) {breathing}\b|\bno chest pain (?:or|and) {breathing}\b", text))
    no_speaking = bool(re.search(rf"\b(?:no|without) {speaking}\b|\bno (?:chest pain|{breathing}) (?:or|and) {speaking}\b", text))
    not_awake = bool(re.search(r"\bnot awake\b|\bunresponsive\b", text))
    return SafetyAnswers(
        awake_and_responsive=False if not_awake else True if "awake and responsive" in text else None,
        chest_pain=False if no_chest else True if "chest pain" in text else None,
        severe_trouble_breathing=False if no_breathing else True if re.search(rf"\b{breathing}\b", text) else None,
        difficulty_speaking=False if no_speaking else True if re.search(rf"\b{speaking}\b", text) else None,
        new_or_worsening_confusion=True if "confusion is new" in text or "new confusion" in text else None,
    )


class HomeSafetyAgent:
    def __init__(self, tools: HomeSafetyTools):
        self.tools = tools

    async def assess(self, household_id: str):
        return await self.tools.run_home_safety_sweep(household_id)


class CareCoordinatorAgent:
    def __init__(self, tools: CareCoordinatorTools):
        self.tools = tools

    async def on_call(self, household_id: str):
        return await self.tools.find_on_call_contact(household_id)


class LogisticsRoutineAgent:
    def __init__(self, tools: LogisticsRoutineTools):
        self.tools = tools

    async def overview(self, household_id: str):
        return await self.tools.get_upcoming_appointments(household_id)


class FullCareCircleSupervisor:
    def __init__(self, triage_agent: TriageSpecialist, store: StateStore, triage: TriageTools, medication: MedicationTools, home: HomeSafetyTools, coordinator: CareCoordinatorTools, logistics: LogisticsRoutineTools, workflow: ActionWorkflow, strands_planner: Any = None):
        self.triage_agent, self.store = triage_agent, store
        self.triage, self.medication = triage, medication
        self.home = HomeSafetyAgent(home)
        self.coordinator = CareCoordinatorAgent(coordinator)
        self.logistics = LogisticsRoutineAgent(logistics)
        self.workflow = workflow
        self.workflow.coordinator_tools = coordinator
        self.strands_planner = strands_planner

    async def coordinate(self, request: CareRequest) -> CareResponse:
        overall_started = perf_counter()
        if self.store.get_profile(request.household_id) is None:
            raise KeyError("UnknownHousehold")
        trace: list[dict[str, Any]] = []
        emit("CareCircle Supervisor", "coordinate", "RUNNING")

        async def step(component: str, operation: str, call):
            started = perf_counter()
            emit(component, operation, "RUNNING")
            try:
                value = await call
                success = True
                return value
            except Exception:
                success = False
                raise
            finally:
                item = {"component": component, "operation": operation, "success": success, "latency_ms": round((perf_counter()-started)*1000, 2)}
                trace.append(item)
                log_event("orchestration_step", session_id=request.session_id, **item)
                emit(component, operation, "COMPLETE" if success else "FAILED", latency_ms=item["latency_ms"])

        if request.incident_id:
            incident = self.store.get_incident(request.incident_id)
            if not incident or incident["household_id"] != request.household_id:
                raise KeyError("UnknownIncident")
            intent = _continuation_intent(request.utterance)
            if intent is None:
                raise ValueError("UnsupportedIncidentContinuation")
            response = await self._continue_demo(request, incident, intent, step, trace)
            incident = self.store.get_incident(request.incident_id)
            response.awaiting_safety_answers = bool(incident.get("awaiting_safety_answers"))
            incident["trace"] = incident.get("trace", []) + trace
            self.store.update_incident(request.incident_id, incident)
            emit("CareCircle Supervisor", "coordinate", "COMPLETE", latency_ms=round((perf_counter()-overall_started)*1000, 2))
            if response.approval_required:
                emit("CareCircle Supervisor", "approval", "NEEDS_APPROVAL")
            return response

        if self.strands_planner is not None:
            try:
                await step("CareCircle Supervisor", "strands_agents_as_tools_plan", self.strands_planner.plan(request))
            except Exception:
                # Advisory routing cannot override deterministic safety routing.
                pass

        try:
            triage = await step("Triage Agent", "assess", self.triage_agent.assess(request))
        except Exception:
            created = await step("DynamoDB", "create_incident", self.triage.create_incident(request.household_id, request.session_id, "Care status could not be confirmed.", "unknown"))
            incident_id = created.data["incident"]["incident_id"]
            alert = await step("Care Coordinator Agent", "prepare_caregiver_alert", self.coordinator.tools.prepare_caregiver_alert(request.household_id, incident_id, "Please review the unconfirmed care concern."))
            action = alert.data["action"]
            log_event("supervisor_completed", trace_id=incident_id, session_id=request.session_id, incident_id=incident_id, selected_specialists=["triage"], policy_outcome="safe_fallback", outcome="fallback")
            return CareResponse(incident_id=incident_id, summary="Care coordination could not be completed. Follow the household care/emergency plan and seek appropriate human help for urgent concerns.", risk_level="unknown", evidence=[Evidence(source="carecircle", description="Care status has not been confirmed.")], proposed_actions=[ProposedAction(action_id=action["action_id"], type="notify_primary_caregiver", description=action["description"], requires_confirmation=True)], completed_actions=[], approval_required=True, next_check_at=None, trace=trace)
        created = await step("DynamoDB", "create_incident", self.triage.create_incident(request.household_id, request.session_id, "Care concern requires review." if triage.incident_requires_review else "Routine care request.", triage.risk_level))
        incident_id = created.data["incident"]["incident_id"]
        answers = {rule: True for rule in triage.red_flags if rule in SafetyAnswers.model_fields}
        if "not_awake_or_responsive" in triage.red_flags:
            answers["awake_and_responsive"] = False
        await step("Triage Agent", "get_emergency_plan", self.triage.get_emergency_plan(request.household_id))
        await step("Triage Agent", "collect_safety_answers", self.triage.collect_safety_answers(incident_id, SafetyAnswers(**answers)))
        await step("Safety Policy", "evaluate_red_flag_rules", self.triage.evaluate_red_flag_rules(SafetyAnswers(**answers)))
        evidence = list(triage.evidence)
        selected = ["triage"]
        if triage.stop_normal_orchestration:
            plan = await step("Triage Agent", "get_emergency_plan", self.triage.get_emergency_plan(request.household_id))
            response = CareResponse(incident_id=incident_id, summary=plan.data["plan"], risk_level="high", evidence=evidence, proposed_actions=[], completed_actions=[], approval_required=False, next_check_at=None, trace=trace)
        else:
            await step("Triage Agent", "get_recent_anomalies", self.triage.get_recent_anomalies(request.household_id))
            if triage.medication_related:
                selected.append("medication")
                missed = await step("Medication Agent", "find_missed_doses", self.medication.find_missed_doses(request.household_id))
                if missed.data["unresolved"]:
                    evidence.append(Evidence(source="medication", description="The morning medication status is unresolved."))
            selected.append("home_safety")
            home = await step("Home Safety Agent", "run_home_safety_sweep", self.home.assess(request.household_id))
            evidence.append(Evidence(source="home_safety", description=home.data["entry"]["summary"]))
            selected.append("care_coordinator")
            contact = await step("Care Coordinator Agent", "find_on_call_contact", self.coordinator.on_call(request.household_id))
            if contact.data["contact"]:
                incident = self.store.get_incident(incident_id)
                incident["assigned_caregiver"] = contact.data["contact"]["id"]
                self.store.update_incident(incident_id, incident)
            actions: list[ProposedAction] = []
            if triage.incident_requires_review:
                if not triage.safety_questions:
                    alert = await step("Care Coordinator Agent", "prepare_caregiver_alert", self.coordinator.tools.prepare_caregiver_alert(request.household_id, incident_id, "Please review the reported care concern."))
                    action = alert.data["action"]
                    actions.append(ProposedAction(action_id=action["action_id"], type="notify_primary_caregiver", description=action["description"], requires_confirmation=True))
                    await step("Care Coordinator Agent", "update_care_task", self.coordinator.tools.update_care_task(request.household_id, "morning-check", "ASSIGNED"))
                    incident = self.store.get_incident(incident_id)
                    incident["care_task_status"] = "ASSIGNED"
                    self.store.update_incident(incident_id, incident)
                else:
                    incident = self.store.get_incident(incident_id)
                    incident["awaiting_safety_answers"] = True
                    self.store.update_incident(incident_id, incident)
            summary = ("Is Dad awake and responsive? Does he have chest pain, difficulty breathing, or trouble speaking?" if triage.safety_questions else
                       "The morning medication status is unresolved and the reported change in confusion requires caregiver review." if triage.medication_related and triage.incident_requires_review else "Care status reviewed; follow the household care plan.")
            response = CareResponse(incident_id=incident_id, summary=summary, risk_level="unknown" if triage.safety_questions else triage.risk_level, evidence=evidence, proposed_actions=actions, completed_actions=[], approval_required=bool(actions), next_check_at=None, trace=trace)
        incident = self.store.get_incident(incident_id)
        response.awaiting_safety_answers = bool(incident.get("awaiting_safety_answers"))
        trace.append({"component": "CareCircle Supervisor", "operation": "coordinate", "success": True, "latency_ms": round((perf_counter()-overall_started)*1000, 2)})
        incident["evidence"] = [x.model_dump() for x in response.evidence]
        incident["trace"] = trace
        self.store.update_incident(incident_id, incident)
        log_event("supervisor_completed", trace_id=incident_id, session_id=request.session_id, incident_id=incident_id, selected_specialists=selected, policy_outcome="emergency_stop" if triage.stop_normal_orchestration else "caregiver_review" if triage.incident_requires_review else "normal", outcome="success")
        emit("CareCircle Supervisor", "coordinate", "COMPLETE", latency_ms=round((perf_counter()-overall_started)*1000, 2))
        if response.approval_required:
            emit("CareCircle Supervisor", "approval", "NEEDS_APPROVAL")
        return response

    async def _continue_demo(self, request, incident, intent, step, trace) -> CareResponse:
        household_id, incident_id = request.household_id, request.incident_id
        evidence: list[Evidence] = []
        actions: list[ProposedAction] = []
        summary = "Care status reviewed."
        if intent == "safety_answers":
            if not incident.get("awaiting_safety_answers"):
                raise ValueError("SafetyAnswerNotPending")
            answers = _spoken_safety_answers(request.utterance)
            collected = await step("Triage Agent", "collect_safety_answers", self.triage.collect_safety_answers(incident_id, answers))
            # The tool persists the merge. Carry it into this snapshot before the
            # final incident write, or that write would erase the new answers.
            incident["safety_answers"] = collected.data["answers"]
            combined = SafetyAnswers(**collected.data["answers"])
            policy = await step("Safety Policy", "evaluate_red_flag_rules", self.triage.evaluate_red_flag_rules(combined))
            if policy.data["evaluation"]["has_emergency_red_flag"]:
                plan = await step("Triage Agent", "get_emergency_plan", self.triage.get_emergency_plan(household_id))
                summary = plan.data["plan"]
                incident["emergency_stop"] = True
                incident["awaiting_safety_answers"] = False
            elif _missing_safety_question(combined):
                summary = _missing_safety_question(combined)
            else:
                contact = await step("Care Coordinator Agent", "find_on_call_contact", self.coordinator.on_call(household_id))
                if contact.data["contact"]:
                    incident["assigned_caregiver"] = contact.data["contact"]["id"]
                alert = await step("Care Coordinator Agent", "prepare_caregiver_alert", self.coordinator.tools.prepare_caregiver_alert(household_id, incident_id, "Please review the reported care concern."))
                action = alert.data["action"]
                actions.append(ProposedAction(action_id=action["action_id"], type="notify_primary_caregiver", description=action["description"], requires_confirmation=True))
                await step("Care Coordinator Agent", "update_care_task", self.coordinator.tools.update_care_task(household_id, "morning-check", "ASSIGNED"))
                incident["care_task_status"] = "ASSIGNED"
                incident["awaiting_safety_answers"] = False
                summary = "No immediate emergency red flag was confirmed. The new confusion and unresolved medication need caregiver review; John is the available backup caregiver."
            self.store.update_incident(incident_id, incident)
        elif intent == "device":
            state = await step("Home Safety Agent", "get_stove_or_smart_plug_status", self.home.tools.get_stove_or_smart_plug_status(household_id))
            if state.data["status"].get("smart_plug") == "on":
                prepared = await step("Home Safety Agent", "request_device_action", self.home.tools.request_device_action(household_id, incident_id, "stove-plug", "turn_off"))
                action = prepared.data["action"]
                actions.append(ProposedAction(action_id=action["action_id"], type="device_change", description="Turn off the simulated kitchen smart plug.", requires_confirmation=True))
                summary = "The simulated kitchen smart plug is on. Turning it off requires your approval."
            else:
                summary = "The simulated kitchen smart plug is already off."
        elif intent == "drafts":
            await step("Medication Agent", "get_medication_inventory", self.medication.get_medication_inventory(household_id))
            appointment, _, _ = await asyncio.gather(
                step("Logistics & Routine Agent", "get_upcoming_appointments", self.logistics.tools.get_upcoming_appointments(household_id)),
                step("Logistics & Routine Agent", "get_daily_routine", self.logistics.tools.get_daily_routine(household_id)),
                step("Logistics & Routine Agent", "get_pharmacy_details", self.logistics.tools.get_pharmacy_details(household_id)),
            )
            existing = {x["type"] for x in self.store.list_actions(incident_id)}
            requests = (("refill_draft", "Medication Agent", self.medication.prepare_refill_request(household_id, incident_id, "med-heart-001")),
                        ("ride_draft", "Logistics & Routine Agent", self.logistics.tools.prepare_ride_request(household_id, incident_id, appointment.data["appointments"][0]["id"])),
                        ("supply_draft", "Logistics & Routine Agent", self.logistics.tools.prepare_supply_request(household_id, incident_id, "weekly pill organizer")))
            for kind, component, call in requests:
                if kind not in existing:
                    prepared = await step(component, kind, call)
                    evidence.append(Evidence(source="prepared_draft", description=prepared.data["action"]["description"]))
                else:
                    call.close()
            summary = "Prepared drafts for a medication refill, the 2:30 PM cardiology ride, and a weekly pill organizer. Nothing was purchased, booked, or sent to a pharmacy."
        elif intent == "resolution":
            if incident.get("emergency_stop"):
                raise ValueError("EmergencyIncidentCannotBeAutoResolved")
            dose = await step("Medication Agent", "record_dose_status", self.medication.record_dose_status(household_id, "med-heart-001", "taken", f"dose-confirm-{incident_id}", incident_id))
            task = await step("Care Coordinator Agent", "update_care_task", self.coordinator.tools.update_care_task(household_id, "morning-check", "COMPLETED"))
            incident["status"] = "RESOLVED"
            incident["resolution_state"] = "RESOLVED"
            incident["care_task_status"] = "COMPLETED"
            self.store.update_incident(incident_id, incident)
            supersede_follow_up_escalation(self.store, incident_id)
            evidence.extend((Evidence(source="caregiver_report", description="John reported that Dad confirmed taking the morning medication."),
                             Evidence(source="care_task", description=f"Morning check is {task.data['task']['status'].lower()}.")))
            summary = "John's check and Dad's reported morning dose were recorded. The caregiver task and incident are resolved; this is a recorded fact, not dosing advice."
        return CareResponse(incident_id=incident_id, summary=summary, risk_level="unknown" if incident.get("awaiting_safety_answers") else incident["risk_level"],
                            evidence=evidence, proposed_actions=actions, completed_actions=[],
                            approval_required=bool(actions), next_check_at=None, trace=trace)

    async def briefing(self, household_id: str) -> HouseholdBriefing:
        profile = self.store.get_profile(household_id)
        if profile is None:
            raise KeyError("UnknownHousehold")
        async def specialist(component: str, operation: str, call):
            started = perf_counter()
            emit(component, operation, "RUNNING")
            try:
                value = await call
            except BaseException:
                emit(component, operation, "FAILED", latency_ms=round((perf_counter()-started)*1000, 2))
                raise
            emit(component, operation, "COMPLETE", latency_ms=round((perf_counter()-started)*1000, 2))
            return value

        operations = [
            ("medication", specialist("Medication Agent", "find_missed_doses", self.medication.find_missed_doses(household_id))),
            ("inventory", specialist("Medication Agent", "get_medication_inventory", self.medication.get_medication_inventory(household_id))),
            ("home", specialist("Home Safety Agent", "run_home_safety_sweep", self.home.assess(household_id))),
            ("coordinator", specialist("Care Coordinator Agent", "get_care_team", self.coordinator.tools.get_care_team(household_id))),
            ("logistics", specialist("Logistics & Routine Agent", "get_upcoming_appointments", self.logistics.overview(household_id))),
            ("routine", specialist("Logistics & Routine Agent", "get_daily_routine", self.logistics.tools.get_daily_routine(household_id))),
            ("pharmacy", specialist("Logistics & Routine Agent", "get_pharmacy_details", self.logistics.tools.get_pharmacy_details(household_id))),
        ]
        values = await asyncio.gather(*(call for _, call in operations), return_exceptions=True)
        domains = {name: value for (name, _), value in zip(operations, values)}
        unavailable = [name for name, value in domains.items() if isinstance(value, BaseException)]
        incidents = [x["incident_id"] for x in self.store.list_incidents(household_id)
                     if x["resolution_state"] != "RESOLVED"
                     and (household_id != "demo-household" or is_current_demo_event(profile, {"timestamp": x.get("created_at")}))]
        return HouseholdBriefing(
            household_id=household_id,
            medication_status=None if "medication" in unavailable else domains["medication"].data,
            home_status=None if "home" in unavailable else domains["home"].data,
            open_care_tasks=[x for x in profile["care_tasks"] if x["status"] != "COMPLETED" and x.get("owner")],
            next_appointment=None if "logistics" in unavailable else next(iter(domains["logistics"].data["appointments"]), None),
            routine_deviations=[x for x in self.store.list_events(household_id)
                                if x.get("kind") == "routine_exception"
                                and (household_id != "demo-household" or is_current_demo_event(profile, x))],
            unresolved_incidents=incidents,
            unavailable_domains=unavailable,
            care_team=[] if "coordinator" in unavailable else domains["coordinator"].data["contacts"],
        )
