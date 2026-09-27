"""Provider-backed medication fact retrieval; contains no dosing logic."""
from datetime import date

from carecircle.providers.medication import MedicationProvider
from carecircle.schemas import Evidence, MedicationAssessment


class MedicationAgent:
    def __init__(self, provider: MedicationProvider):
        self._provider = provider

    async def assess(self, household_id: str, on_date: date | None = None) -> MedicationAssessment:
        assessment_date = on_date or date.today()
        schedule = await self._provider.get_medication_schedule(household_id)
        history = await self._provider.get_dose_history(household_id, assessment_date)
        inventory = await self._provider.get_medication_inventory(household_id)
        unresolved = [dose for dose in history if dose.status == "unresolved"]

        if not schedule:
            return MedicationAssessment(
                scheduled_medications=[], unresolved_doses=[], inventory_notes=[],
                evidence=[Evidence(
                    source="medication",
                    description="No synthetic medication records were found for this household.",
                )],
            )

        names = {item.id: item.display_name for item in schedule}
        evidence = [Evidence(
            source="medication",
            description=f"The {dose.scheduled_at.strftime('%-I:%M %p')} {names.get(dose.medication_id, 'medication')} has no recorded dose status.",
        ) for dose in unresolved]
        notes = [f"{names.get(medication_id, 'Medication')}: {count} doses remain in recorded inventory."
                 for medication_id, count in inventory.items()]
        evidence.extend(Evidence(source="medication", description=note) for note in notes)
        return MedicationAssessment(
            scheduled_medications=schedule,
            unresolved_doses=unresolved,
            inventory_notes=notes,
            evidence=evidence,
        )
