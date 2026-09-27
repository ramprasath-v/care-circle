from datetime import datetime, timezone
from unittest.mock import MagicMock

from carecircle.providers.aws_actions import EventBridgeSchedulerProvider, SnsAlertProvider


def test_sns_provider_targets_only_reviewed_topic_and_carries_demo_routing():
    client = MagicMock()
    client.publish.return_value = {"MessageId": "sns-message-1"}
    topic = "arn:aws:sns:us-east-1:109837542034:CareCircleCaregiverAlerts"
    result = SnsAlertProvider(topic, client).send("action-1", "Controlled message", "incident-1", "demo-household", "maya")
    assert result == {"message_id": "sns-message-1", "provider": "sns", "status": "published"}
    args = client.publish.call_args.kwargs
    assert args["TopicArn"] == topic
    assert args["MessageAttributes"]["CareCircleOwner"]["StringValue"] == "maya"
    assert args["MessageAttributes"]["CareCircleIncidentId"]["StringValue"] == "incident-1"


def test_scheduler_provider_creates_bounded_one_shot_lambda_schedule():
    client = MagicMock()
    provider = EventBridgeSchedulerProvider("arn:aws:lambda:us-east-1:109837542034:function:CareCircleFollowUp", "arn:aws:iam::109837542034:role/CareCircleFollowUpSchedulerRole", client)
    provider.schedule("incident-1", "demo-household", datetime(2026, 9, 20, 12, 30, tzinfo=timezone.utc))
    args = client.create_schedule.call_args.kwargs
    assert args["Name"] == "carecircle-incident-1"
    assert args["ScheduleExpression"] == "at(2026-09-20T12:30:00)"
    assert args["ActionAfterCompletion"] == "DELETE"
    assert args["Target"]["Arn"].endswith(":function:CareCircleFollowUp")
