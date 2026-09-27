"""CareCircle's three-table state boundary and deterministic demo seed."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from threading import RLock
from typing import Any, Protocol


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


DEMO_PROFILE: dict[str, Any] = {
    "household_id": "demo-household",
    "person": {"id": "dad", "name": "Robert"},
    "consent": {"caregiver_alerts": False},
    "emergency_plan": "Contact Maya and follow the household emergency plan; seek appropriate human emergency help for urgent symptoms.",
    "care_team": [
        {"id": "maya", "name": "Maya", "relationship": "daughter", "role": "primary caregiver", "on_call": False},
        {"id": "john", "name": "John", "relationship": "backup caregiver", "role": "backup caregiver", "on_call": True},
    ],
    "medications": [{"id": "med-heart-001", "display_name": "Morning heart medication", "scheduled_time": "08:00", "inventory_count": 4}],
    "routine": [{"id": "breakfast", "time": "07:30", "name": "Breakfast"}, {"id": "medication", "time": "08:00", "name": "Medication"}, {"id": "walk", "time": "09:00", "name": "Morning walk"}],
    "appointments": [{"id": "cardiology", "time": "14:30", "name": "Cardiology appointment", "date": "today"}],
    "pharmacy": {"id": "demo-pharmacy", "name": "Demo Pharmacy", "contact": "Synthetic demo record"},
    "devices": [{"id": "front-door", "type": "door"}, {"id": "stove-plug", "type": "smart_plug", "state": "on"}],
    "care_tasks": [{"id": "morning-check", "title": "Confirm morning medication status", "status": "OPEN", "owner": None}],
}


def is_current_demo_event(profile: dict[str, Any], event: dict[str, Any]) -> bool:
    """Hide historical demo events from a reset generation without deleting them."""
    started = profile.get("demo_started_at")
    if not started:
        return True
    try:
        return datetime.fromisoformat(event["timestamp"].replace("Z", "+00:00")) >= datetime.fromisoformat(started.replace("Z", "+00:00"))
    except (KeyError, ValueError, TypeError):
        return False


class StateStore(Protocol):
    def get_profile(self, household_id: str) -> dict[str, Any] | None: ...
    def put_profile(self, household_id: str, profile: dict[str, Any]) -> None: ...
    def put_event(self, household_id: str, event_id: str, event: dict[str, Any]) -> bool: ...
    def list_events(self, household_id: str) -> list[dict[str, Any]]: ...
    def put_incident(self, incident_id: str, incident: dict[str, Any]) -> bool: ...
    def get_incident(self, incident_id: str) -> dict[str, Any] | None: ...
    def update_incident(self, incident_id: str, incident: dict[str, Any]) -> None: ...
    def put_action(self, incident_id: str, action_id: str, action: dict[str, Any]) -> bool: ...
    def get_action(self, incident_id: str, action_id: str) -> dict[str, Any] | None: ...
    def update_action(self, incident_id: str, action_id: str, action: dict[str, Any]) -> None: ...
    def claim_action(self, incident_id: str, action_id: str) -> bool: ...
    def list_actions(self, incident_id: str) -> list[dict[str, Any]]: ...
    def list_incidents(self, household_id: str) -> list[dict[str, Any]]: ...


class InMemoryStateStore:
    def __init__(self, seed: bool = True):
        self._lock = RLock()
        self.profiles: dict[str, dict[str, Any]] = {}
        self.events: dict[str, dict[str, dict[str, Any]]] = {}
        self.incidents: dict[str, dict[str, Any]] = {}
        self.actions: dict[tuple[str, str], dict[str, Any]] = {}
        if seed:
            profile = self._copy(DEMO_PROFILE)
            profile["demo_started_at"] = now_iso()
            self.put_profile("demo-household", profile)
            self.put_event("demo-household", "dose-morning", {"event_id": "dose-morning", "kind": "dose_status", "medication_id": "med-heart-001", "status": "unresolved", "timestamp": now_iso()})
            self.put_event("demo-household", "routine-walk", {"event_id": "routine-walk", "kind": "routine_exception", "routine_id": "walk", "status": "not_observed", "timestamp": now_iso()})

    @staticmethod
    def _copy(value: Any) -> Any:
        return json.loads(json.dumps(value))

    def get_profile(self, household_id: str) -> dict[str, Any] | None:
        with self._lock:
            x = self.profiles.get(household_id)
            return self._copy(x) if x else None

    def put_profile(self, household_id: str, profile: dict[str, Any]) -> None:
        with self._lock:
            self.profiles[household_id] = self._copy(profile)

    def put_event(self, household_id: str, event_id: str, event: dict[str, Any]) -> bool:
        with self._lock:
            items = self.events.setdefault(household_id, {})
            if event_id in items:
                return False
            items[event_id] = self._copy(event)
            return True

    def list_events(self, household_id: str) -> list[dict[str, Any]]:
        with self._lock:
            return sorted((self._copy(x) for x in self.events.get(household_id, {}).values()), key=lambda x: x.get("timestamp", ""), reverse=True)

    def put_incident(self, incident_id: str, incident: dict[str, Any]) -> bool:
        with self._lock:
            if incident_id in self.incidents:
                return False
            self.incidents[incident_id] = self._copy(incident)
            return True

    def get_incident(self, incident_id: str) -> dict[str, Any] | None:
        with self._lock:
            x = self.incidents.get(incident_id)
            return self._copy(x) if x else None

    def update_incident(self, incident_id: str, incident: dict[str, Any]) -> None:
        with self._lock:
            if incident_id not in self.incidents:
                raise KeyError(incident_id)
            self.incidents[incident_id] = self._copy(incident)

    def put_action(self, incident_id: str, action_id: str, action: dict[str, Any]) -> bool:
        with self._lock:
            key = (incident_id, action_id)
            if key in self.actions:
                return False
            self.actions[key] = self._copy(action)
            return True

    def get_action(self, incident_id: str, action_id: str) -> dict[str, Any] | None:
        with self._lock:
            x = self.actions.get((incident_id, action_id))
            return self._copy(x) if x else None

    def update_action(self, incident_id: str, action_id: str, action: dict[str, Any]) -> None:
        with self._lock:
            key = (incident_id, action_id)
            if key not in self.actions:
                raise KeyError(key)
            self.actions[key] = self._copy(action)

    def claim_action(self, incident_id: str, action_id: str) -> bool:
        with self._lock:
            x = self.actions.get((incident_id, action_id))
            if not x or x.get("execution_state") != "PENDING":
                return False
            x["execution_state"] = "EXECUTING"
            x["attempts"] = x.get("attempts", 0) + 1
            return True

    def list_actions(self, incident_id: str) -> list[dict[str, Any]]:
        with self._lock:
            return [self._copy(v) for (iid, _), v in self.actions.items() if iid == incident_id]

    def list_incidents(self, household_id: str) -> list[dict[str, Any]]:
        with self._lock:
            return [self._copy(x) for x in self.incidents.values() if x.get("household_id") == household_id]


class DynamoStateStore:
    """Three-table adapter. JSON payloads retain strict schema while keys stay queryable."""
    def __init__(self, profiles_table: str, events_table: str, ledger_table: str, dynamodb: Any = None):
        import boto3
        db = dynamodb or boto3.resource("dynamodb")
        self.profiles = db.Table(profiles_table)
        self.events = db.Table(events_table)
        self.ledger = db.Table(ledger_table)

    @staticmethod
    def _value(item: dict[str, Any] | None) -> dict[str, Any] | None:
        return json.loads(item["payload"]) if item else None

    @staticmethod
    def _conditional(table: Any, item: dict[str, Any]) -> bool:
        from botocore.exceptions import ClientError
        try:
            table.put_item(Item=item, ConditionExpression="attribute_not_exists(#pk)", ExpressionAttributeNames={"#pk": next(iter(item))})
            return True
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
                return False
            raise

    def get_profile(self, household_id: str) -> dict[str, Any] | None:
        return self._value(self.profiles.get_item(Key={"household_id": household_id, "sk": "PROFILE"}, ConsistentRead=True).get("Item"))

    def put_profile(self, household_id: str, profile: dict[str, Any]) -> None:
        self.profiles.put_item(Item={"household_id": household_id, "sk": "PROFILE", "payload": json.dumps(profile)})

    def put_event(self, household_id: str, event_id: str, event: dict[str, Any]) -> bool:
        if any(x.get("event_id") == event_id for x in self.list_events(household_id)):
            return False
        return self._conditional(self.events, {"household_id": household_id, "sk": f"{event.get('timestamp', now_iso())}#{event_id}", "event_id": event_id, "payload": json.dumps(event)})

    def list_events(self, household_id: str) -> list[dict[str, Any]]:
        from boto3.dynamodb.conditions import Key
        items = self.events.query(KeyConditionExpression=Key("household_id").eq(household_id), ScanIndexForward=False, ConsistentRead=True).get("Items", [])
        return [self._value(x) for x in items]

    def put_incident(self, incident_id: str, incident: dict[str, Any]) -> bool:
        return self._conditional(self.ledger, {"incident_id": incident_id, "action_id": "INCIDENT", "household_id": incident["household_id"], "payload": json.dumps(incident)})

    def get_incident(self, incident_id: str) -> dict[str, Any] | None:
        return self._value(self.ledger.get_item(Key={"incident_id": incident_id, "action_id": "INCIDENT"}, ConsistentRead=True).get("Item"))

    def update_incident(self, incident_id: str, incident: dict[str, Any]) -> None:
        self.ledger.update_item(Key={"incident_id": incident_id, "action_id": "INCIDENT"}, UpdateExpression="SET #p = :p", ConditionExpression="attribute_exists(incident_id)", ExpressionAttributeNames={"#p": "payload"}, ExpressionAttributeValues={":p": json.dumps(incident)})

    def put_action(self, incident_id: str, action_id: str, action: dict[str, Any]) -> bool:
        return self._conditional(self.ledger, {"incident_id": incident_id, "action_id": action_id, "payload": json.dumps(action), "execution_state": action.get("execution_state", "PENDING")})

    def get_action(self, incident_id: str, action_id: str) -> dict[str, Any] | None:
        return self._value(self.ledger.get_item(Key={"incident_id": incident_id, "action_id": action_id}, ConsistentRead=True).get("Item"))

    def update_action(self, incident_id: str, action_id: str, action: dict[str, Any]) -> None:
        self.ledger.update_item(Key={"incident_id": incident_id, "action_id": action_id}, UpdateExpression="SET #p = :p, execution_state = :s", ConditionExpression="attribute_exists(incident_id)", ExpressionAttributeNames={"#p": "payload"}, ExpressionAttributeValues={":p": json.dumps(action), ":s": action.get("execution_state", "PENDING")})

    def claim_action(self, incident_id: str, action_id: str) -> bool:
        from botocore.exceptions import ClientError
        try:
            self.ledger.update_item(Key={"incident_id": incident_id, "action_id": action_id}, UpdateExpression="SET execution_state = :e", ConditionExpression="execution_state = :p", ExpressionAttributeValues={":e": "EXECUTING", ":p": "PENDING"})
            return True
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
                return False
            raise

    def list_actions(self, incident_id: str) -> list[dict[str, Any]]:
        from boto3.dynamodb.conditions import Key
        items = self.ledger.query(KeyConditionExpression=Key("incident_id").eq(incident_id), ConsistentRead=True).get("Items", [])
        return [self._value(x) for x in items if x["action_id"] != "INCIDENT"]

    def list_incidents(self, household_id: str) -> list[dict[str, Any]]:
        from boto3.dynamodb.conditions import Attr
        items = self.ledger.scan(FilterExpression=Attr("action_id").eq("INCIDENT") & Attr("household_id").eq(household_id), ConsistentRead=True).get("Items", [])
        return [self._value(x) for x in items]


def seed_demo(store: StateStore) -> None:
    if store.get_profile("demo-household") is None:
        profile = json.loads(json.dumps(DEMO_PROFILE))
        profile["demo_started_at"] = now_iso()
        store.put_profile("demo-household", profile)
    if not any(x.get("event_id") == "dose-morning" for x in store.list_events("demo-household")):
        store.put_event("demo-household", "dose-morning", {"event_id": "dose-morning", "kind": "dose_status", "medication_id": "med-heart-001", "status": "unresolved", "timestamp": now_iso()})
    if not any(x.get("event_id") == "routine-walk" for x in store.list_events("demo-household")):
        store.put_event("demo-household", "routine-walk", {"event_id": "routine-walk", "kind": "routine_exception", "routine_id": "walk", "status": "not_observed", "timestamp": now_iso()})
