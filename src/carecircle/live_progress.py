"""Read real, session-correlated AgentCore progress records from CloudWatch Logs."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any


class CloudWatchProgressSource:
    def __init__(self, runtime_arn: str, region: str = "us-east-1", profile: str | None = None, client: Any = None):
        if client is None:
            import boto3
            client = boto3.Session(profile_name=profile, region_name=region).client("logs")
        self.client = client
        runtime_id = runtime_arn.rsplit("/", 1)[-1]
        self.log_group = f"/aws/bedrock-agentcore/runtimes/{runtime_id}-DEFAULT"

    def fetch(self, session_id: str, started_ms: int) -> list[dict[str, Any]]:
        values: list[dict[str, Any]] = []
        token = None
        for _ in range(5):
            request = {"logGroupName": self.log_group, "startTime": max(0, started_ms - 5000),
                       "filterPattern": f'"{session_id}"', "limit": 100}
            if token:
                request["nextToken"] = token
            response = self.client.filter_log_events(**request)
            for item in response.get("events", []):
                try:
                    record = json.loads(item["message"])
                except (ValueError, KeyError):
                    continue
                if record.get("session_id") != session_id or record.get("event") not in {"carecircle_progress", "mcp_tool_invoked"}:
                    continue
                record = {key: record[key] for key in (
                    "event", "session_id", "component", "operation", "status", "provider",
                    "latency_ms", "message", "tool", "approval_status", "kind",
                ) if key in record}
                record["event_id"] = item["eventId"]
                record["timestamp"] = datetime.fromtimestamp(item["timestamp"] / 1000, timezone.utc).isoformat()
                values.append(record)
            next_token = response.get("nextToken")
            if not next_token or next_token == token:
                break
            token = next_token
        return values
