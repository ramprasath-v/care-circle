"""Home device boundary; the demo simulator never controls a real home."""
from __future__ import annotations

from typing import Any, Protocol


class RingProvider(Protocol):
    async def recent_events(self, household_id: str) -> list[dict[str, Any]]: ...
    async def smoke_co_status(self, household_id: str) -> dict[str, Any]: ...
    async def stove_status(self, household_id: str) -> dict[str, Any]: ...
    async def execute_device_action(self, household_id: str, device_id: str, command: str) -> dict[str, Any]: ...


class SimulatedRingProvider:
    def __init__(self, store=None):
        self.store = store
        self._plug_state = "on"
        self._demo_started_at: str | None = None
        self.executed: dict[tuple[str, str, str], dict[str, Any]] = {}

    def reset_demo_state(self) -> None:
        """Discard this simulator instance's results from previous demo runs."""
        self._plug_state = "on"
        self._demo_started_at = None
        self.executed = {key: value for key, value in self.executed.items() if key[0] != "demo-household"}

    def _sync_demo_generation(self, profile: dict[str, Any]) -> None:
        generation = profile.get("demo_started_at")
        if generation != self._demo_started_at:
            if self.executed:
                self.reset_demo_state()
            self._demo_started_at = generation

    async def recent_events(self, household_id: str) -> list[dict[str, Any]]:
        if household_id != "demo-household":
            return []
        return [
            {"device_id": "front-door", "event": "opened", "time": "07:42", "source": "simulated-ring"},
        ]

    async def smoke_co_status(self, household_id: str) -> dict[str, Any]:
        return {"smoke": "normal", "co": "normal", "source": "simulated-ring"} if household_id == "demo-household" else {"status": "unavailable"}

    async def stove_status(self, household_id: str) -> dict[str, Any]:
        if household_id != "demo-household":
            return {"status": "unavailable"}
        profile = self.store.get_profile(household_id) if self.store else None
        if profile:
            self._sync_demo_generation(profile)
        device = next((x for x in profile.get("devices", []) if x["id"] == "stove-plug"), None) if profile else None
        state = device.get("state", "unavailable") if device else ("unavailable" if self.store else self._plug_state)
        return {"stove": "off", "smart_plug": state,
                "source": "simulated-ring"}

    async def execute_device_action(self, household_id: str, device_id: str, command: str) -> dict[str, Any]:
        if household_id != "demo-household" or device_id != "stove-plug" or command != "turn_off":
            raise ValueError("UnsupportedSimulatedDeviceAction")
        key = (household_id, device_id, command)
        if self.store:
            profile = self.store.get_profile(household_id)
            self._sync_demo_generation(profile)
            device = next((x for x in profile["devices"] if x["id"] == device_id), None)
            if device is None:
                raise KeyError("UnknownDemoDevice")
            device["state"] = "off"
            self.store.put_profile(household_id, profile)
        # A store-backed simulator reads the persisted profile on every request.
        # Keep the local fallback only for storeless tests; it must not outlive a demo reset.
        if self.store is None:
            self._plug_state = "off"
        result = self.executed.setdefault(key, {"device_id": device_id, "command": command, "status": "simulated_executed", "source": "simulated-ring"})
        return dict(result)
