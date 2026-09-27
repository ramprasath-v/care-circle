from datetime import date

from carecircle.agents.medication import MedicationAgent
from carecircle.providers.medication import InMemoryMedicationProvider


async def test_schedule_retrieval():
    schedule = await InMemoryMedicationProvider().get_medication_schedule("demo-household")
    assert schedule[0].id == "med-heart-001"
    assert schedule[0].scheduled_time.hour == 8


async def test_unresolved_dose_detection():
    assessment = await MedicationAgent(InMemoryMedicationProvider()).assess(
        "demo-household", date(2026, 9, 18)
    )
    assert len(assessment.unresolved_doses) == 1
    assert assessment.unresolved_doses[0].status == "unresolved"


async def test_inventory_retrieval():
    inventory = await InMemoryMedicationProvider().get_medication_inventory("demo-household")
    assert inventory == {"med-heart-001": 4}


async def test_unknown_household_is_safe():
    assessment = await MedicationAgent(InMemoryMedicationProvider()).assess("unknown")
    assert assessment.scheduled_medications == []
    assert assessment.unresolved_doses == []
    assert "No synthetic medication records" in assessment.evidence[0].description


async def test_medication_agent_does_not_generate_dosing_advice():
    assessment = await MedicationAgent(InMemoryMedicationProvider()).assess("demo-household")
    rendered = assessment.model_dump_json().lower()
    for prohibited in ("take another", "skip a dose", "double", "change dosage", "change medication timing"):
        assert prohibited not in rendered
