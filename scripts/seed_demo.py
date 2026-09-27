"""Seed only deterministic synthetic records in the three CareCircle tables."""
from __future__ import annotations

import json
import os

import boto3
from botocore.exceptions import ClientError

from carecircle.state import DEMO_PROFILE, DynamoStateStore, seed_demo


def main() -> None:
    session = boto3.Session(profile_name=os.getenv("AWS_PROFILE", "carecircle-admin"), region_name=os.getenv("AWS_REGION", "us-east-1"))
    db = session.resource("dynamodb")
    store = DynamoStateStore("CareCircleCareProfiles", "CareCircleCareEvents", "CareCircleActionLedger", db)
    seed_demo(store)
    table = db.Table("CareCircleCareProfiles")
    profile = DEMO_PROFILE
    records = [
        ("PERSON#dad", profile["person"]),
        *[(f"CONTACT#{x['id']}", x) for x in profile["care_team"]],
        *[(f"MED#{x['id']}", x) for x in profile["medications"]],
        *[(f"DEVICE#{x['id']}", x) for x in profile["devices"]],
        *[(f"ROUTINE#{x['id']}", x) for x in profile["routine"]],
        *[(f"APPOINTMENT#{x['id']}", x) for x in profile["appointments"]],
        ("PHARMACY#demo-pharmacy", profile["pharmacy"]),
    ]
    for sk, payload in records:
        try:
            table.put_item(Item={"household_id": "demo-household", "sk": sk, "payload": json.dumps(payload)}, ConditionExpression="attribute_not_exists(sk)")
        except ClientError as exc:
            if exc.response["Error"]["Code"] != "ConditionalCheckFailedException":
                raise
    print(f"seeded_household=demo-household profile_records={len(records)+1} event_seed=dose-morning")


if __name__ == "__main__":
    main()
