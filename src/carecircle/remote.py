"""IAM-authenticated MCP client shared by integration checks and the local demo UI."""
from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

import boto3


class RemoteCareCircle:
    def __init__(self, runtime_arn: str, profile: str | None = None, region: str = "us-east-1", client: Any = None):
        self.runtime_arn = runtime_arn
        self.client = client or boto3.Session(profile_name=profile, region_name=region).client("bedrock-agentcore")

    @staticmethod
    def _decode(response: dict[str, Any]) -> dict[str, Any]:
        raw = response["response"].read().decode("utf-8")
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            lines = [line[5:].strip() for line in raw.splitlines() if line.startswith("data:")]
            if not lines:
                raise
            return json.loads(lines[-1])

    def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        session_id = f"carecircle-web-{uuid4().hex}"
        base = {"agentRuntimeArn": self.runtime_arn, "qualifier": "DEFAULT", "runtimeSessionId": session_id, "contentType": "application/json", "accept": "application/json, text/event-stream", "mcpProtocolVersion": "2025-11-25"}
        init = self.client.invoke_agent_runtime(**base, mcpMethod="initialize", payload=json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-11-25", "capabilities": {}, "clientInfo": {"name": "carecircle-web", "version": "1"}}}).encode())
        init_result = self._decode(init)
        if init_result.get("result", {}).get("protocolVersion") != "2025-11-25":
            raise RuntimeError("McpInitializationFailed")
        request = {**base, "mcpMethod": "tools/call", "mcpName": name, "payload": json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": name, "arguments": arguments}}).encode()}
        if init.get("mcpSessionId"):
            request["mcpSessionId"] = init["mcpSessionId"]
        response = self._decode(self.client.invoke_agent_runtime(**request))
        value = response.get("result", {})
        if value.get("isError") or "structuredContent" not in value:
            raise RuntimeError("McpToolFailed")
        return value["structuredContent"]
