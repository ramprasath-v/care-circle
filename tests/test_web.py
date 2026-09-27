from pathlib import Path

import httpx

from carecircle.web import create_web_app


class FakeRemote:
    def __init__(self):
        self.calls = []

    def call(self, operation, arguments):
        self.calls.append((operation, arguments))
        return {"household_id": "demo-household", "unavailable_domains": []}


async def test_alexa_simulator_proxies_to_remote_without_browser_credentials():
    remote = FakeRemote()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_web_app(remote)), base_url="http://localhost") as client:
        page = await client.get("/")
        assert page.status_code == 200
        assert "Execution trace" in page.text and "Approve" in page.text
        assert "AWS_SECRET_ACCESS_KEY" not in page.text
        result = await client.post("/api/mcp", json={"operation": "get_household_briefing", "arguments": {"household_id": "demo-household"}})
        assert result.status_code == 200
        assert remote.calls == [("get_household_briefing", {"household_id": "demo-household"})]
        unknown = await client.post("/api/mcp", json={"operation": "internal_tool", "arguments": {}})
        assert unknown.status_code == 400
