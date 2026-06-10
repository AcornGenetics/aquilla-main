import json
import os
import uuid

import boto3
import psycopg

_UUID_NS = uuid.UUID("a1b2c3d4-e5f6-7890-abcd-ef1234567890")


def handler(event, context):
    s3 = boto3.client("s3")
    dsn = os.environ["DB_DSN"]

    for record in event.get("Records", []):
        bucket = record["s3"]["bucket"]["name"]
        key = record["s3"]["object"]["key"]
        obj = s3.get_object(Bucket=bucket, Key=key)
        data = json.loads(obj["Body"].read())
        _upsert(dsn, data["device_id"], data["event"])


def _upsert(dsn: str, device_id: str, event: dict) -> None:
    payload = event.get("payload", {})
    run_timestamp = payload.get("run_timestamp") or event.get("created_at")
    run_id = str(uuid.uuid5(_UUID_NS, f"{device_id}:{run_timestamp}"))
    protocol = payload.get("profile") or payload.get("protocol", "")
    aborted = bool(payload.get("aborted", False))

    conn = psycopg.connect(dsn)
    with conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO devices (device_id) VALUES (%s) ON CONFLICT DO NOTHING",
                (device_id,),
            )
            cur.execute(
                """
                INSERT INTO runs
                    (run_id, device_id, protocol, run_name, run_timestamp, duration_seconds, aborted)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT DO NOTHING
                """,
                (
                    run_id,
                    device_id,
                    protocol,
                    payload.get("run_name", ""),
                    run_timestamp,
                    payload.get("duration_seconds"),
                    aborted,
                ),
            )
            if not aborted:
                for call in payload.get("calls", []):
                    cur.execute(
                        """
                        INSERT INTO run_results
                            (run_id, device_id, protocol, well, channel, call, cq, run_timestamp)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (run_id, well, channel) DO NOTHING
                        """,
                        (
                            run_id,
                            device_id,
                            protocol,
                            call.get("well"),
                            call.get("channel"),
                            call.get("call"),
                            call.get("cq"),
                            run_timestamp,
                        ),
                    )
