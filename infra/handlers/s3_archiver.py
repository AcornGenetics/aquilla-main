import json
import os
from datetime import datetime, timezone

import boto3


def handler(event, context):
    s3 = boto3.client("s3")
    bucket = os.environ["S3_BUCKET"]

    for record in event.get("Records", []):
        body = json.loads(record["body"])
        device_id = body["device_id"]
        evt = body["event"]
        event_id = str(evt.get("id", "unknown"))
        date_prefix = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        key = f"{date_prefix}/{device_id}/{event_id}.json"
        s3.put_object(
            Bucket=bucket,
            Key=key,
            Body=json.dumps(body),
            ContentType="application/json",
        )
