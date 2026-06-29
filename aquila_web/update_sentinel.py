"""OTA update completion sentinel (issue #183, ADR-018).

A tiny on-disk record at /opt/fleet/last_update.json that survives the Watchtower
container swap and the post-update reboot, letting a freshly-started container know
an update just finished. Pure logic only — no FastAPI, no hardware imports.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone


def write_sentinel(path: str, state: str, ts: str, target_digest: str | None = None) -> None:
    """Persist the sentinel record to ``path``.

    ``target_digest`` (the image digest we are trying to install) is recorded when
    given, so the post-update boot can verify what actually booted. Omitting it keeps
    the legacy two-field record for callers that don't need verification.
    """
    record: dict = {"state": state, "ts": ts}
    if target_digest:
        record["target_digest"] = target_digest
    with open(path, "w") as f:
        json.dump(record, f)


def classify_update(target_digest: str | None, running_digest: str | None) -> str:
    """Pure verdict on whether an update applied, by image-digest comparison.

    Returns:
      "complete" — the running image matches the target (update applied).
      "failed"   — both digests are known and differ (old image still running).
      "unknown"  — either digest is missing; the caller cannot tell and must stay
                   optimistic (treat as complete) rather than show a false failure.
    """
    if not target_digest or not running_digest:
        return "unknown"
    return "complete" if running_digest == target_digest else "failed"


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
      "show_failed"   — we are back up after a verified-failed update; surface the
                        failure modal.
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
    if state == "show_failed":
        return "show_failed"
    return "none"
