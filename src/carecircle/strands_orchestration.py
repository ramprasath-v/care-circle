"""Strands supervisor with five read-only specialist agents as tools.

Its plan is advisory. Deterministic code in FullCareCircleSupervisor always performs
triage and safety-policy evaluation and is the sole owner of mutations.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field
from strands import Agent, tool
from strands.models import BedrockModel

from carecircle.internal_tools import CareCoordinatorTools, HomeSafetyTools, LogisticsRoutineTools, MedicationTools, TriageTools
from carecircle.schemas import CareRequest


class SupervisorPlan(BaseModel):
    selected_specialists: list[Literal["triage", "medication", "home_safety", "care_coordinator", "logistics_routine"]] = Field(default_factory=list)


class StrandsSupervisorPlanner:
    def __init__(self, model_id: str, region: str, triage: TriageTools, medication: MedicationTools, home: HomeSafetyTools, coordinator: CareCoordinatorTools, logistics: LogisticsRoutineTools):
        self.model_id, self.region = model_id, region
        self.triage, self.medication, self.home = triage, medication, home
        self.coordinator, self.logistics = coordinator, logistics

    async def plan(self, request: CareRequest) -> SupervisorPlan:
        model = BedrockModel(model_id=self.model_id, region_name=self.region)

        @tool
        async def get_recent_anomalies(household_id: str) -> str:
            """Read recent household anomalies for triage context."""
            return (await self.triage.get_recent_anomalies(household_id)).model_dump_json()

        @tool
        async def get_medication_schedule(household_id: str) -> str:
            """Read recorded medication schedule without giving dosing advice."""
            return (await self.medication.get_medication_schedule(household_id)).model_dump_json()

        @tool
        async def run_home_safety_sweep(household_id: str) -> str:
            """Read simulated home safety context without changing devices."""
            return (await self.home.run_home_safety_sweep(household_id)).model_dump_json()

        @tool
        async def get_care_team(household_id: str) -> str:
            """Read the synthetic household caregiver team."""
            return (await self.coordinator.get_care_team(household_id)).model_dump_json()

        @tool
        async def get_upcoming_appointments(household_id: str) -> str:
            """Read upcoming synthetic appointments."""
            return (await self.logistics.get_upcoming_appointments(household_id)).model_dump_json()

        specialists = [
            Agent(name="triage_agent", description="Read-only triage context", model=model, system_prompt="Report recorded anomalies only.", tools=[get_recent_anomalies], callback_handler=None),
            Agent(name="medication_agent", description="Recorded medication facts", model=model, system_prompt="Report recorded medication facts only; never advise a dose.", tools=[get_medication_schedule], callback_handler=None),
            Agent(name="home_safety_agent", description="Simulated home safety context", model=model, system_prompt="Report recorded home safety facts only.", tools=[run_home_safety_sweep], callback_handler=None),
            Agent(name="care_coordinator_agent", description="Care team context", model=model, system_prompt="Report recorded care team facts only; never send alerts.", tools=[get_care_team], callback_handler=None),
            Agent(name="logistics_routine_agent", description="Appointments and routine context", model=model, system_prompt="Report recorded appointment facts only; never book or purchase.", tools=[get_upcoming_appointments], callback_handler=None),
        ]
        supervisor = Agent(name="carecircle_supervisor", description="CareCircle conversation planner", model=model, system_prompt="Select relevant specialist agents as tools for this synthetic care request. Return only selected specialist names. Never decide emergency rules, approvals, or external actions.", tools=specialists, callback_handler=None)
        response = await supervisor.invoke_async(request.model_dump_json(), structured_output_model=SupervisorPlan)
        return SupervisorPlan.model_validate(response.structured_output)
