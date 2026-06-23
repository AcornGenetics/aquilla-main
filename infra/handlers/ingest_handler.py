import json
import os
import boto3


def handler(event, context):
    try:
        body = json.loads(event.get("body") or "{}")
    except json.JSONDecodeError:
        return _resp(400, {"error": "invalid JSON"})

    device_id = body.get("device_id")
    events = body.get("events")

    if not device_id or events is None:
        return _resp(400, {"error": "missing device_id or events"})

    sqs = boto3.client("sqs", region_name=os.environ.get("AWS_REGION", "us-east-1"))
    queue_url = os.environ["SQS_QUEUE_URL"]

    for evt in events:
        sqs.send_message(
            QueueUrl=queue_url,
            MessageBody=json.dumps({"device_id": device_id, "event": evt}),
        )

    return _resp(200, {"queued": len(events)})


def _resp(status_code: int, body: dict) -> dict:
    return {"statusCode": status_code, "body": json.dumps(body)}
