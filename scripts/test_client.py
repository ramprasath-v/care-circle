"""Invoke the local CareCircle MCP endpoint using the official SDK."""
import argparse
import asyncio
import json
from datetime import timedelta

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from carecircle.schemas import CareResponse


async def run(url: str) -> None:
    async with streamablehttp_client(url, timeout=timedelta(seconds=120)) as (read, write, _):
        async with ClientSession(read, write, read_timeout_seconds=timedelta(seconds=120)) as session:
            initialized = await session.initialize()
            if initialized.protocolVersion < "2025-11-25":
                raise RuntimeError("MCP protocol 2025-11-25 or later is required")
            result = await session.call_tool("coordinate_care_request", {
                "household_id": "demo-household", "actor_role": "caregiver",
                "utterance": "Dad says he may have missed his morning medication and seems confused.",
                "session_id": "demo-session",
            })
            if result.isError:
                raise RuntimeError("MCP tool returned an error")
            response = CareResponse.model_validate_json(json.dumps(result.structuredContent))
            print(response.model_dump_json(indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8000/mcp")
    asyncio.run(run(parser.parse_args().url))
