import json
from contextlib import asynccontextmanager

import httpx

from carecircle.app import create_server
from carecircle.schemas import CareResponse, ConfirmationResult, HouseholdBriefing, IncidentStatus
from test_full_build import full_stack


@asynccontextmanager
async def client_for(supervisor):
    server = create_server(supervisor)
    app = server.streamable_http_app()
    async with server.session_manager.run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://localhost:8000", headers={"Accept": "application/json, text/event-stream", "MCP-Protocol-Version": "2025-11-25", "Mcp-Session-Id": "full-build-test"}) as client:
            yield client


async def call(client, name, arguments):
    response = await client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": arguments}})
    assert response.status_code == 200
    value = response.json()["result"]
    assert not value.get("isError"), value
    return value["structuredContent"]


async def test_four_public_contracts_and_approval(full_stack):
    async with client_for(full_stack.supervisor) as client:
        briefing = HouseholdBriefing.model_validate(await call(client, "get_household_briefing", {"household_id": "demo-household"}))
        assert briefing.next_appointment["time"] == "14:30"
        response = CareResponse.model_validate(await call(client, "coordinate_care_request", {"household_id": "demo-household", "actor_role": "caregiver", "utterance": "Dad says he may have missed his morning medication and seems confused.", "session_id": "mcp-full"}))
        confirmed = ConfirmationResult.model_validate_json(json.dumps(await call(client, "confirm_action", {"household_id": "demo-household", "incident_id": response.incident_id, "action_id": response.proposed_actions[0].action_id, "approved": True})))
        assert confirmed.provider_result["provider"] == "simulated-sns"
        status = IncidentStatus.model_validate_json(json.dumps(await call(client, "get_incident_status", {"household_id": "demo-household", "incident_id": response.incident_id})))
        assert status.completed_actions and status.assigned_caregiver == "john"


async def test_unknown_household_is_rejected_at_public_boundary(full_stack):
    async with client_for(full_stack.supervisor) as client:
        response = await client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "get_household_briefing", "arguments": {"household_id": "unknown"}}})
        assert response.status_code == 200
        assert response.json()["result"]["isError"]
