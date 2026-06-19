"""OTA update completion sentinel (issue #183, ADR-016).

A tiny on-disk record at /opt/fleet/last_update.json that survives the Watchtower
container swap and the post-update reboot, letting a freshly-started container know
an update just finished. Pure logic only — no FastAPI, no hardware imports.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone


def write_sentinel(path: str, state: str, ts: str) -> None:
    """Persist the sentinel record {state, ts} to ``path``."""
    with open(path, "w") as f:
        json.dump({"state": state, "ts": ts}, f)


def read_sentinel(path: str) -> dict | None:
    """Return the sentinel record, or None if missing/unreadable."""
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def clear_sentinel(path: str) -> None:
    """Delete the sentinel if present; idempotent."""
    try:
        os.remove(path)
    except OSError:
        pass


def _age_seconds(ts: str, now: datetime) -> float | None:
    """Seconds between the sentinel timestamp and ``now``; None if ts is unparseable."""
    try:
        recorded = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None
    if recorded.tzinfo is None:
        recorded = recorded.replace(tzinfo=timezone.utc)
    # Tolerate a naive `now` (e.g. datetime.utcnow()) by treating it as UTC.
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return (now - recorded).total_seconds()


def next_startup_action(record: dict | None, now: datetime, ttl_seconds: int) -> str:
    """Decide what a freshly-started container should do given the sentinel.

    Returns one of:
      "reboot"        — an update just applied; trigger the host reboot (caller first
                        advances the sentinel to ``show_complete`` so it fires once).
      "show_complete" — we are back up after the reboot; surface the completion modal.
      "none"          — no sentinel, unparseable, or older than the TTL (ignore/clear).
    """
    if not record:
        return "none"
    age = _age_seconds(record.get("ts", ""), now)
    if age is None or age > ttl_seconds:
        return "none"
    state = record.get("state")
    if state == "reboot_pending":
        return "reboot"
    if state == "show_complete":
        return "show_complete"
    return "none"
