"""Reset only synthetic voice/browser demo records; never touch other households."""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from carecircle.state import DEMO_PROFILE, DynamoStateStore, InMemoryStateStore, StateStore, now_iso


def reset_voice_demo(store: StateStore, scheduler_client: Any = None, ring_provider: Any = None) -> dict[str, int]:
    household = "demo-household"
    incidents = [item for item in store.list_incidents(household)
                 if item.get("session_id", "").startswith(("voice-", "web-"))]
    ids = {item["incident_id"] for item in incidents}
    # Cancel only schedules recorded on those exact voice-demo incidents, before removing their ledger.
    if scheduler_client:
        from botocore.exceptions import ClientError
        for incident in incidents:
            schedule = incident.get("follow_up_schedule") or {}
            name = schedule.get("schedule_name")
            if schedule.get("provider") != "eventbridge-scheduler" or name != f"carecircle-{incident['incident_id']}":
                continue
            try:
                scheduler_client.delete_schedule(Name=name)
            except ClientError as exc:
                if exc.response["Error"]["Code"] != "ResourceNotFoundException":
                    raise
    deleted_events = 0
    if isinstance(store, InMemoryStateStore):
        for key in list(store.actions):
            if key[0] in ids:
                del store.actions[key]
        for incident_id in ids:
            del store.incidents[incident_id]
        for event_id, event in list(store.events.get(household, {}).items()):
            if event.get("incident_id") in ids:
                del store.events[household][event_id]
                deleted_events += 1
    elif isinstance(store, DynamoStateStore):
        from boto3.dynamodb.conditions import Key
        for incident_id in ids:
            for action in store.list_actions(incident_id):
                store.ledger.delete_item(Key={"incident_id": incident_id, "action_id": action["action_id"]})
            store.ledger.delete_item(Key={"incident_id": incident_id, "action_id": "INCIDENT"})
        kwargs = {"KeyConditionExpression": Key("household_id").eq(household), "ConsistentRead": True}
        while True:
            page = store.events.query(**kwargs)
            for item in page["Items"]:
                event = store._value(item)
                if event.get("incident_id") in ids:
                    store.events.delete_item(Key={"household_id": household, "sk": item["sk"]})
                    deleted_events += 1
            if "LastEvaluatedKey" not in page:
                break
            kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]
    else:
        raise TypeError("UnsupportedStateStoreForDemoReset")
    profile = deepcopy(DEMO_PROFILE)
    generation = now_iso()
    profile["demo_started_at"] = generation
    store.put_profile(household, profile)
    if ring_provider is not None:
        ring_provider.reset_demo_state()
    # Existing canonical event IDs may belong to an older demo generation. Always
    # write fresh facts after the new boundary; historical events stay untouched.
    dose_id = f"dose-morning-{generation}"
    walk_id = f"routine-walk-{generation}"
    store.put_event(household, dose_id, {"event_id": dose_id, "kind": "dose_status",
                                       "medication_id": "med-heart-001", "status": "unresolved", "timestamp": now_iso()})
    store.put_event(household, walk_id, {"event_id": walk_id, "kind": "routine_exception",
                                       "routine_id": "walk", "status": "not_observed", "timestamp": now_iso()})
    return {"incidents": len(ids), "events": deleted_events}
