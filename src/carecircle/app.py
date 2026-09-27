"""Four-tool MCP Streamable HTTP server for AgentCore Runtime."""
import logging
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from carecircle.config import Settings
from carecircle.schemas import CareRequest, CareResponse, ConfirmationResult, HouseholdBriefing, IncidentStatus, NonEmpty
from carecircle.supervisor import CareCircleSupervisor, build_specialists, log_event
from carecircle.full_supervisor import FullCareCircleSupervisor
from carecircle.internal_tools import CareCoordinatorTools, HomeSafetyTools, LogisticsRoutineTools, MedicationTools, TriageTools
from carecircle.providers.aws_actions import EventBridgeSchedulerProvider, RecordingAlertProvider, RecordingSchedulerProvider, SnsAlertProvider
from carecircle.providers.ring import SimulatedRingProvider
from carecircle.progress import emit, progress_session
from carecircle.state import DynamoStateStore, InMemoryStateStore
from carecircle.strands_orchestration import StrandsSupervisorPlanner
from carecircle.workflow import ActionWorkflow


def create_server(supervisor: CareCircleSupervisor | FullCareCircleSupervisor) -> FastMCP:
    server = FastMCP(
        "CareCircle", host="0.0.0.0", port=8000,
        streamable_http_path="/mcp", stateless_http=True, json_response=True,
        # AgentCore forwards its own Host header; edge access is controlled by AWS.
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )

    @server.tool()
    async def coordinate_care_request(
        household_id: NonEmpty, actor_role: NonEmpty, utterance: NonEmpty, session_id: NonEmpty,
        incident_id: NonEmpty | None = None,
    ) -> CareResponse:
        """Coordinate a synthetic care request; propose actions without executing them."""
        request = CareRequest(household_id=household_id, actor_role=actor_role,
                              utterance=utterance, session_id=session_id, incident_id=incident_id)
        log_event("mcp_tool_invoked", tool="coordinate_care_request", session_id=request.session_id)
        with progress_session(request.session_id):
            return await supervisor.coordinate(request)

    @server.tool()
    async def get_household_briefing(household_id: NonEmpty, session_id: NonEmpty | None = None) -> HouseholdBriefing:
        """Summarize recorded medication, home, care-team and routine state."""
        log_event("mcp_tool_invoked", tool="get_household_briefing", session_id=session_id)
        with progress_session(session_id):
            emit("CareCircle Supervisor", "briefing", "RUNNING")
            value = await supervisor.briefing(household_id)
            emit("CareCircle Supervisor", "briefing", "COMPLETE")
            return value

    @server.tool()
    async def confirm_action(household_id: NonEmpty, incident_id: NonEmpty, action_id: NonEmpty, approved: bool, session_id: NonEmpty | None = None) -> ConfirmationResult:
        """Apply deterministic approval policy to a persisted action."""
        log_event("mcp_tool_invoked", tool="confirm_action", session_id=session_id, incident_id=incident_id, approval_status="approved" if approved else "rejected")
        with progress_session(session_id):
            return await supervisor.workflow.confirm(household_id, incident_id, action_id, approved)

    @server.tool()
    async def get_incident_status(household_id: NonEmpty, incident_id: NonEmpty, session_id: NonEmpty | None = None) -> IncidentStatus:
        """Read a persisted incident and its action ledger."""
        log_event("mcp_tool_invoked", tool="get_incident_status", session_id=session_id, incident_id=incident_id)
        with progress_session(session_id):
            emit("DynamoDB", "get_incident_status", "RUNNING")
            value = supervisor.workflow.status(household_id, incident_id)
            emit("DynamoDB", "get_incident_status", "COMPLETE", provider="ActionLedger")
            return value

    return server


def main() -> None:
    settings = Settings()
    logging.basicConfig(level=settings.log_level.upper(), format="%(message)s")
    # Third-party debug logs can include prompts; keep them out of application logs.
    for name in ("strands", "botocore", "boto3", "mcp", "httpx"):
        logging.getLogger(name).setLevel(logging.CRITICAL)
    triage_agent, _ = build_specialists(settings)
    if all((settings.care_profiles_table, settings.care_events_table, settings.action_ledger_table)):
        store = DynamoStateStore(settings.care_profiles_table, settings.care_events_table, settings.action_ledger_table)
    else:
        store = InMemoryStateStore()
    ring = SimulatedRingProvider(store)
    alerts = SnsAlertProvider(settings.caregiver_alert_topic_arn) if settings.caregiver_alert_topic_arn else RecordingAlertProvider()
    scheduler = EventBridgeSchedulerProvider(settings.follow_up_lambda_arn, settings.follow_up_scheduler_role_arn) if settings.follow_up_lambda_arn and settings.follow_up_scheduler_role_arn else RecordingSchedulerProvider()
    workflow = ActionWorkflow(store, alerts, scheduler, ring, demo_mode=settings.demo_mode)
    triage_tools = TriageTools(store)
    medication_tools = MedicationTools(store)
    home_tools = HomeSafetyTools(store, ring)
    coordinator_tools = CareCoordinatorTools(store, alerts, scheduler)
    logistics_tools = LogisticsRoutineTools(store)
    planner = StrandsSupervisorPlanner(settings.bedrock_model_id, settings.aws_region, triage_tools, medication_tools, home_tools, coordinator_tools, logistics_tools)
    supervisor = FullCareCircleSupervisor(triage_agent, store, triage_tools, medication_tools, home_tools, coordinator_tools, logistics_tools, workflow, planner)
    create_server(supervisor).run(transport="streamable-http")


if __name__ == "__main__":
    main()
