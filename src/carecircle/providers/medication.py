"""Synthetic medication provider for Phase 2."""
from datetime import date, datetime, time
from typing import Protocol

from carecircle.schemas import DoseRecord, MedicationRecord


class MedicationProvider(Protocol):
    async def get_medication_schedule(self, household_id: str) -> list[MedicationRecord]: ...
    async def get_dose_history(self, household_id: str, on_date: date) -> list[DoseRecord]: ...
    async def get_medication_inventory(self, household_id: str) -> dict[str, int]: ...


class InMemoryMedicationProvider:
    """Fixed synthetic records. No data in this provider represents a real person."""

    async def get_medication_schedule(self, household_id: str) -> list[MedicationRecord]:
        if household_id != "demo-household":
            return []
        return [MedicationRecord(
            id="med-heart-001",
            display_name="Morning heart medication",
            scheduled_time=time(8, 0),
            inventory_count=4,
        )]

    async def get_dose_history(self, household_id: str, on_date: date) -> list[DoseRecord]:
        if household_id != "demo-household":
            return []
        return [DoseRecord(
            medication_id="med-heart-001",
            scheduled_at=datetime.combine(on_date, time(8, 0)),
            status="unresolved",
        )]

    async def get_medication_inventory(self, household_id: str) -> dict[str, int]:
        return {item.id: item.inventory_count for item in await self.get_medication_schedule(household_id)}
