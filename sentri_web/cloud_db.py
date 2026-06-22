import json
import os
from datetime import datetime
from typing import Any

try:
    import psycopg
except ModuleNotFoundError:  # pragma: no cover - optional dependency
    psycopg = None


def _utc_now() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


def get_cloud_db_dsn() -> str:
    return os.getenv("AQ_CLOUD_DB_DSN", "").strip()


def get_cloud_events_table() -> str:
    return os.getenv("AQ_CLOUD_DB_TABLE", "cloud_events")


def _connect() -> "psycopg.Connection":
    if psycopg is None:
        raise RuntimeError("psycopg is required for cloud ingest")
    dsn = get_cloud_db_dsn()
    if not dsn:
        raise ValueError("AQ_CLOUD_DB_DSN is required for cloud ingest")
    return psycopg.connect(dsn)


def init_cloud_db() -> None:
    table = get_cloud_events_table()
    with _connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {table} (
                    id BIGSERIAL PRIMARY KEY,
                    event_id BIGINT,
                    device_id TEXT,
                    event_type TEXT NOT NULL,
                    payload JSONB NOT NULL,
                    created_at TIMESTAMPTZ,
                    received_at TIMESTAMPTZ NOT NULL
                )
                """
            )
            cursor.execute(
                f"""
                CREATE UNIQUE INDEX IF NOT EXISTS {table}_device_event
                ON {table} (device_id, event_id)
                """
            )
        connection.commit()


def save_cloud_events(device_id: str | None, events: list[dict[str, Any]]) -> int:
    if not events:
        return 0
    init_cloud_db()
    table = get_cloud_events_table()
    records = []
    received_at = _utc_now()
    for event in events:
        if not isinstance(event, dict):
            continue
        event_type = event.get("event_type")
        payload = event.get("payload")
        if not event_type or payload is None:
            continue
        resolved_device_id = event.get("device_id") or device_id
        records.append(
            (
                event.get("id"),
                resolved_device_id,
                event_type,
                json.dumps(payload),
                event.get("created_at"),
                received_at,
            )
        )
    if not records:
        return 0
    with _connect() as connection:
        with connection.cursor() as cursor:
            cursor.executemany(
                f"""
                INSERT INTO {table} (
                    event_id,
                    device_id,
                    event_type,
                    payload,
                    created_at,
                    received_at
                )
                VALUES (%s, %s, %s, %s::jsonb, %s, %s)
                ON CONFLICT (device_id, event_id) DO NOTHING
                """,
                records,
            )
        connection.commit()
    return len(records)
