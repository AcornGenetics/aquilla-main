import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from config import get_src_basedir


def _utc_now() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


def get_db_path() -> Path:
    env_path = os.getenv("AQ_LOCAL_DB_PATH")
    if env_path:
        return Path(env_path).expanduser()
    return Path(get_src_basedir()).expanduser() / "data" / "db" / "app.db"


def _connect(path: Path | None = None) -> sqlite3.Connection:
    resolved_path = path or get_db_path()
    resolved_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(resolved_path)
    connection.row_factory = sqlite3.Row
    return connection


def init_local_db() -> None:
    with _connect() as connection:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                payload TEXT NOT NULL,
                device_id TEXT,
                created_at TEXT NOT NULL,
                synced_at TEXT
            )
            """
        )


def enqueue_event(event_type: str, payload: dict[str, Any], device_id: str | None = None) -> int:
    resolved_device_id = device_id or os.getenv("AQ_SYNC_DEVICE_ID") or os.getenv("DEVICE_ID")
    with _connect() as connection:
        cursor = connection.execute(
            """
            INSERT INTO events (event_type, payload, device_id, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (event_type, json.dumps(payload), resolved_device_id, _utc_now()),
        )
        return int(cursor.lastrowid)


def get_pending_events(limit: int = 100) -> list[dict[str, Any]]:
    with _connect() as connection:
        rows = connection.execute(
            """
            SELECT id, event_type, payload, device_id, created_at
            FROM events
            WHERE synced_at IS NULL
            ORDER BY id ASC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    results: list[dict[str, Any]] = []
    for row in rows:
        payload = json.loads(row["payload"])
        results.append(
            {
                "id": row["id"],
                "event_type": row["event_type"],
                "payload": payload,
                "device_id": row["device_id"],
                "created_at": row["created_at"],
            }
        )
    return results


def mark_event_synced(event_ids: list[int]) -> None:
    if not event_ids:
        return
    placeholders = ",".join("?" for _ in event_ids)
    query = f"UPDATE events SET synced_at = ? WHERE id IN ({placeholders})"
    values = [_utc_now(), *event_ids]
    with _connect() as connection:
        connection.execute(query, values)


def cleanup_synced_events(retain_days: int = 7) -> int:
    with _connect() as connection:
        cursor = connection.execute(
            """
            DELETE FROM events
            WHERE synced_at IS NOT NULL
            AND synced_at < datetime('now', ?)
            """,
            (f"-{retain_days} days",),
        )
        return int(cursor.rowcount or 0)
