"""Invoke a deployed MCP runtime through IAM-authenticated AgentCore APIs."""
import json
import os
from time import perf_counter
from typing import Any
from uuid import uuid4

import boto3

from carecircle.schemas import CareResponse

PROTOCOL_VERSION = "2025-11-25"


def read_json_response(response: dict[str, Any]) -> dict[str, Any]:
    raw = response["response"].read().decode("utf-8")
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        data_lines = [line[5:].strip() for line in raw.splitlines() if line.startswith("data:")]
        if not data_lines:
            raise
        return json.loads(data_lines[-1])


def invoke(
    client: Any,
    runtime_arn: str,
    runtime_session_id: str,
    payload: dict[str, Any],
    *,
    mcp_session_id: str | None = None,
) -> tuple[dict[str, Any], str | None]:
    request: dict[str, Any] = {
        "agentRuntimeArn": runtime_arn,
        "qualifier": "DEFAULT",
        "runtimeSessionId": runtime_session_id,
        "contentType": "application/json",
        "accept": "application/json, text/event-stream",
        "mcpProtocolVersion": PROTOCOL_VERSION,
        "mcpMethod": payload["method"],
        "payload": json.dumps(payload).encode("utf-8"),
    }
    if payload["method"] == "tools/call":
        request["mcpName"] = payload["params"]["name"]
    if mcp_session_id:
        request["mcpSessionId"] = mcp_session_id
    response = client.invoke_agent_runtime(**request)
    return read_json_response(response), response.get("mcpSessionId")


def main() -> int:
    runtime_arn = os.environ.get("AGENT_RUNTIME_ARN")
    region = os.environ.get("AWS_REGION")
    profile = os.environ.get("AWS_PROFILE", "default")
    if not runtime_arn or not region:
        print("success=false")
        print("failure_type=MissingConfiguration")
        return 2

    session = boto3.Session(profile_name=profile, region_name=region)
    client = session.client("bedrock-agentcore")
    runtime_session_id = f"carecircle-remote-{uuid4().hex}"
    started = perf_counter()
    try:
        initialize, mcp_session_id = invoke(client, runtime_arn, runtime_session_id, {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "carecircle-remote-check", "version": "1"},
            },
        })
        if initialize.get("result", {}).get("protocolVersion") != PROTOCOL_VERSION:
            raise ValueError("UnexpectedProtocolVersion")

        called, _ = invoke(client, runtime_arn, runtime_session_id, {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "coordinate_care_request",
                "arguments": {
                    "household_id": "demo-household",
                    "actor_role": "caregiver",
                    "utterance": "Dad says he may have missed his morning medication and seems confused.",
                    "session_id": "phase3-remote-demo",
                },
            },
        }, mcp_session_id=mcp_session_id)
        tool_result = called["result"]
        if tool_result.get("isError"):
            raise RuntimeError("McpToolError")
        care_response = CareResponse.model_validate(tool_result["structuredContent"])
    except Exception as exc:
        print("success=false")
        print(f"failure_type={type(exc).__name__}")
        print(f"total_latency_ms={round((perf_counter() - started) * 1000, 2)}")
        return 1

    print("success=true")
    print(f"incident_id={care_response.incident_id}")
    print(f"risk_level={care_response.risk_level}")
    print(f"evidence_count={len(care_response.evidence)}")
    print(f"proposed_action_count={len(care_response.proposed_actions)}")
    print(f"total_latency_ms={round((perf_counter() - started) * 1000, 2)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
