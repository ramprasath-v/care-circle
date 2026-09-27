"""Run the exact CloudFormation inline Lambda source against fake Dynamo tables."""
import json
from pathlib import Path
from unittest.mock import patch

import yaml


class Loader(yaml.SafeLoader):
    pass


Loader.add_multi_constructor("!", lambda loader, suffix, node: loader.construct_scalar(node) if isinstance(node, yaml.ScalarNode) else loader.construct_sequence(node))


class Table:
    def __init__(self):
        self.items = {}

    def get_item(self, Key):
        return {"Item": self.items[tuple(Key.values())]} if tuple(Key.values()) in self.items else {}

    def put_item(self, Item, **kwargs):
        key = (Item.get("incident_id", Item.get("household_id")), Item.get("action_id", Item.get("sk")))
        self.items[key] = Item

    def update_item(self, Key, ExpressionAttributeValues, **kwargs):
        self.items[tuple(Key.values())]["payload"] = ExpressionAttributeValues[":p"]


class DB:
    def __init__(self):
        self.tables = {"CareCircleActionLedger": Table(), "CareCircleCareEvents": Table(), "CareCircleCareProfiles": Table()}

    def Table(self, name):
        return self.tables[name]


def test_inline_lambda_sns_delivery_and_follow_up(monkeypatch):
    import boto3
    monkeypatch.setenv("ACTION_LEDGER_TABLE", "CareCircleActionLedger")
    monkeypatch.setenv("CARE_EVENTS_TABLE", "CareCircleCareEvents")
    monkeypatch.setenv("CARE_PROFILES_TABLE", "CareCircleCareProfiles")
    db = DB()
    source = yaml.load(Path("infra/full-build.yaml").read_text(), Loader=Loader)["Resources"]["FollowUpFunction"]["Properties"]["Code"]["ZipFile"]
    with patch.object(boto3, "resource", return_value=db):
        namespace = {}
        exec(compile(source, "index.py", "exec"), namespace)
    incident = {"incident_id": "incident-1", "household_id": "demo-household", "status": "OPEN", "resolution_state": "UNRESOLVED", "next_check_at": "soon"}
    db.Table("CareCircleActionLedger").put_item({"incident_id": "incident-1", "action_id": "INCIDENT", "payload": json.dumps(incident)})
    db.Table("CareCircleCareProfiles").put_item({"household_id": "demo-household", "sk": "PROFILE", "payload": json.dumps({"care_tasks": [{"id": "morning-check", "status": "OPEN"}]})})
    sns = {"Records": [{"EventSource": "aws:sns", "Sns": {"MessageAttributes": {key: {"Value": value} for key, value in {"CareCircleIncidentId": "incident-1", "CareCircleHouseholdId": "demo-household", "CareCircleActionId": "action-1", "CareCircleOwner": "maya"}.items()}}}]}
    assert namespace["handler"](sns, None)["state"] == "ALERT_DELIVERED"
    assert any(json.loads(x["payload"])["kind"] == "caregiver_alert_delivered" for x in db.Table("CareCircleCareEvents").items.values())
    assert namespace["handler"]({"incident_id": "incident-1", "household_id": "demo-household"}, None)["state"] == "FOLLOW_UP_DUE"
    updated = json.loads(db.Table("CareCircleActionLedger").get_item({"incident_id": "incident-1", "action_id": "INCIDENT"})["Item"]["payload"])
    assert updated["status"] == "FOLLOW_UP_DUE" and updated["next_check_at"] is None
    escalation = db.Table("CareCircleActionLedger").get_item({"incident_id": "incident-1", "action_id": "follow-up-escalation"})["Item"]
    assert json.loads(escalation["payload"])["approval_state"] == "PENDING"
    profile = db.Table("CareCircleCareProfiles").get_item({"household_id": "demo-household", "sk": "PROFILE"})["Item"]
    assert json.loads(profile["payload"])["care_tasks"][0]["status"] == "ASSIGNED"
