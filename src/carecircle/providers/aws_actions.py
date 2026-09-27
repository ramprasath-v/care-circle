"""External action boundaries kept injectable for offline tests."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol


class AlertProvider(Protocol):
    def send(self, action_id: str, message: str, incident_id: str, household_id: str, owner: str) -> dict[str, Any]: ...


class SchedulerProvider(Protocol):
    def schedule(self, incident_id: str, household_id: str, when: datetime) -> dict[str, Any]: ...


class RecordingAlertProvider:
    def __init__(self):
        self.sent: dict[str, dict[str, Any]] = {}

    def send(self, action_id: str, message: str, incident_id: str, household_id: str, owner: str) -> dict[str, Any]:
        return self.sent.setdefault(action_id, {"message_id": f"simulated-{action_id}", "provider": "simulated-sns", "status": "published"})


class SnsAlertProvider:
    def __init__(self, topic_arn: str, client: Any = None):
        import boto3
        self.topic_arn = topic_arn
        self.client = client or boto3.client("sns")

    def send(self, action_id: str, message: str, incident_id: str, household_id: str, owner: str) -> dict[str, Any]:
        attrs = {name: {"DataType": "String", "StringValue": value} for name, value in {"CareCircleActionId": action_id, "CareCircleIncidentId": incident_id, "CareCircleHouseholdId": household_id, "CareCircleOwner": owner}.items()}
        response = self.client.publish(TopicArn=self.topic_arn, Subject="CareCircle caregiver alert", Message=message, MessageAttributes=attrs)
        return {"message_id": response["MessageId"], "provider": "sns", "status": "published"}


class RecordingSchedulerProvider:
    def __init__(self):
        self.scheduled: dict[str, dict[str, Any]] = {}

    def schedule(self, incident_id: str, household_id: str, when: datetime) -> dict[str, Any]:
        return self.scheduled.setdefault(incident_id, {"schedule_name": f"carecircle-{incident_id}", "when": when.isoformat(), "provider": "simulated-eventbridge"})


class EventBridgeSchedulerProvider:
    def __init__(self, target_arn: str, role_arn: str, client: Any = None):
        import boto3
        self.target_arn = target_arn
        self.role_arn = role_arn
        self.client = client or boto3.client("scheduler")

    def schedule(self, incident_id: str, household_id: str, when: datetime) -> dict[str, Any]:
        name = f"carecircle-{incident_id}"
        from botocore.exceptions import ClientError
        try:
            self.client.create_schedule(
                Name=name,
                ScheduleExpression=f"at({when.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S')})",
                ScheduleExpressionTimezone="UTC",
                FlexibleTimeWindow={"Mode": "OFF"},
                ActionAfterCompletion="DELETE",
                Target={"Arn": self.target_arn, "RoleArn": self.role_arn, "Input": json.dumps({"incident_id": incident_id, "household_id": household_id})},
            )
        except ClientError as exc:
            if exc.response["Error"]["Code"] != "ConflictException":
                raise
            self.client.get_schedule(Name=name)
        return {"schedule_name": name, "when": when.isoformat(), "provider": "eventbridge-scheduler"}


def follow_up_time(demo: bool) -> datetime:
    return datetime.now(timezone.utc) + timedelta(minutes=5 if demo else 30)
