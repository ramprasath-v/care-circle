"""Authenticated remote smoke test for briefing, incident, approval, and status."""
from __future__ import annotations

import os
import json
from time import perf_counter

from carecircle.remote import RemoteCareCircle
from carecircle.schemas import CareResponse, ConfirmationResult, HouseholdBriefing, IncidentStatus


def main() -> None:
    remote = RemoteCareCircle(os.environ["AGENT_RUNTIME_ARN"], os.getenv("AWS_PROFILE", "carecircle-admin"), os.getenv("AWS_REGION", "us-east-1"))
    started = perf_counter()
    briefing = HouseholdBriefing.model_validate(remote.call("get_household_briefing", {"household_id": "demo-household"}))
    print(f"briefing_unresolved={len(briefing.medication_status['unresolved'])} home={briefing.home_status['entry']['summary']} appointment={briefing.next_appointment['time']}")
    response = CareResponse.model_validate(remote.call("coordinate_care_request", {"household_id": "demo-household", "actor_role": "caregiver", "utterance": "Dad says he may have missed his morning medication and seems confused.", "session_id": "full-build-remote-demo"}))
    if not response.proposed_actions and "awake and responsive" in response.summary.lower():
        response = CareResponse.model_validate(remote.call("coordinate_care_request", {"household_id": "demo-household", "actor_role": "caregiver", "utterance": "He is awake and responsive. No chest pain or breathing trouble. The confusion is new.", "session_id": "full-build-remote-demo-answer", "incident_id": response.incident_id}))
    print(f"incident_id={response.incident_id} risk={response.risk_level} actions={len(response.proposed_actions)}")
    if not response.approval_required or not response.proposed_actions:
        raise AssertionError("Expected approval action")
    action_id = response.proposed_actions[0].action_id
    confirmation = ConfirmationResult.model_validate_json(json.dumps(remote.call("confirm_action", {"household_id": "demo-household", "incident_id": response.incident_id, "action_id": action_id, "approved": True})))
    print(f"approval={confirmation.approval_state} execution={confirmation.execution_state} provider={confirmation.provider_result} next_check_at={confirmation.next_check_at}")
    if confirmation.execution_state != "COMPLETED" or not confirmation.next_check_at:
        raise AssertionError("Approval did not complete or schedule follow-up")
    status = IncidentStatus.model_validate_json(json.dumps(remote.call("get_incident_status", {"household_id": "demo-household", "incident_id": response.incident_id})))
    print(f"status={status.status} caregiver={status.assigned_caregiver} completed={len(status.completed_actions)} latency_ms={round((perf_counter()-started)*1000,2)}")
    if not status.completed_actions or status.assigned_caregiver != "john":
        raise AssertionError("Persisted status mismatch")


if __name__ == "__main__":
    main()
