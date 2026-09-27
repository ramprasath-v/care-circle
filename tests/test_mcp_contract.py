import json
from contextlib import asynccontextmanager

import httpx
import pytest

from carecircle.app import create_server
from carecircle.schemas import CareResponse
from carecircle.supervisor import CareCircleSupervisor


@pytest.fixture
def client(triage, medication_agent):
    return lambda: connected_client(triage, medication_agent)


@asynccontextmanager
async def connected_client(triage, medication_agent):
    server = create_server(CareCircleSupervisor(triage, medication_agent))
    assert server.settings.host == "0.0.0.0"
    assert server.settings.port == 8000
    app = server.streamable_http_app()
    async with server.session_manager.run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://localhost:8000",
                                    headers={"Accept": "application/json, text/event-stream",
                                             "MCP-Protocol-Version": "2025-11-25",
                                             "Mcp-Session-Id": "agentcore-platform-session"}) as client:
            yield client


async def rpc(client, method, params):
    result = await client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
    assert result.status_code == 200, result.text
    return result.json()


async def test_initialize_and_contract(client, request_data):
    async with client() as client:
        init = await rpc(client, "initialize", {"protocolVersion": "2025-11-25", "capabilities": {},
                                               "clientInfo": {"name": "pytest", "version": "1"}})
        assert init["result"]["protocolVersion"] == "2025-11-25"
        listing = await rpc(client, "tools/list", {})
        tools = listing["result"]["tools"]
        assert len(tools) == 4
        assert {tool["name"] for tool in tools} == {"coordinate_care_request", "get_household_briefing", "confirm_action", "get_incident_status"}
        assert tools[0]["name"] == "coordinate_care_request"
        assert set(tools[0]["inputSchema"]["required"]) == set(request_data)
        assert "risk_level" in tools[0]["outputSchema"]["properties"]
        result = (await rpc(client, "tools/call", {"name": "coordinate_care_request", "arguments": request_data}))["result"]
        assert not result.get("isError")
        response = CareResponse.model_validate_json(json.dumps(result["structuredContent"]))
        assert response.proposed_actions[0].requires_confirmation


@pytest.mark.parametrize("invalid", [{}, {"utterance": ""}, {"household_id": 123}])
async def test_invalid_mcp_input(client, request_data, invalid):
    async with client() as client:
        arguments = {**request_data, **invalid} if invalid else {}
        result = await rpc(client, "tools/call", {"name": "coordinate_care_request", "arguments": arguments})
        assert result.get("error") or result["result"].get("isError")


async def test_model_failure_contract(client, triage, request_data):
    async with client() as client:
        triage.assess.side_effect = RuntimeError("model unavailable")
        result = (await rpc(client, "tools/call", {"name": "coordinate_care_request", "arguments": request_data}))["result"]
        response = CareResponse.model_validate_json(json.dumps(result["structuredContent"]))
        assert response.risk_level == "unknown"
        assert not result.get("isError")
