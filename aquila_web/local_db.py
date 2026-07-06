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
        _add_missing_columns(connection)


# Additive quarantine columns for the size guard (#289). Applied as ALTER TABLE
# so an existing device DB upgrades in place without data loss; idempotent
# because each column is only added when absent.
_QUARANTINE_COLUMNS = {
    "quarantined_at": "TEXT",
    "quarantine_reason": "TEXT",
}


def _add_missing_columns(connection: sqlite3.Connection) -> None:
    existing = {row["name"] for row in connection.execute("PRAGMA table_info(events)")}
    for column, column_type in _QUARANTINE_COLUMNS.items():
        if column not in existing:
            connection.execute(f"ALTER TABLE events ADD COLUMN {column} {column_type}")


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
            WHERE synced_at IS NULL AND quarantined_at IS NULL
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


def mark_event_quarantined(event_id: int, reason: str) -> None:
    """Quarantine one Event that can't Sync even alone (the #289 size guard).

    The row is retained -- never dropped or truncated -- but excluded from
    :func:`get_pending_events` so it can't hold a batch slot or be re-fetched
    every interval. ``reason`` records why for diagnosis.
    """
    with _connect() as connection:
        connection.execute(
            "UPDATE events SET quarantined_at = ?, quarantine_reason = ? WHERE id = ?",
            (_utc_now(), reason, event_id),
        )


def requeue_quarantined_event(event_id: int) -> int:
    """Clear an Event's quarantine so it re-enters the pending queue.

    The recovery seam for the size guard: an event quarantined by a transient
    misconfiguration (e.g. a too-tight cap) can be returned to the flush path
    instead of being stuck forever short of manual SQL. Returns the number of
    rows changed (0 if the event was not quarantined).
    """
    with _connect() as connection:
        cursor = connection.execute(
            "UPDATE events SET quarantined_at = NULL, quarantine_reason = NULL "
            "WHERE id = ? AND quarantined_at IS NOT NULL",
            (event_id,),
        )
        return int(cursor.rowcount or 0)


def get_quarantined_events() -> list[dict[str, Any]]:
    """Quarantined Events, oldest first -- discoverable for diagnosis."""
    with _connect() as connection:
        rows = connection.execute(
            """
            SELECT id, event_type, payload, device_id, created_at,
                   quarantined_at, quarantine_reason
            FROM events
            WHERE quarantined_at IS NOT NULL
            ORDER BY id ASC
            """
        ).fetchall()
    return [
        {
            "id": row["id"],
            "event_type": row["event_type"],
            "payload": json.loads(row["payload"]),
            "device_id": row["device_id"],
            "created_at": row["created_at"],
            "quarantined_at": row["quarantined_at"],
            "quarantine_reason": row["quarantine_reason"],
        }
        for row in rows
    ]


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
