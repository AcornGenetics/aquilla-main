"""OTA update completion sentinel (issue #183, ADR-018).

A tiny on-disk record at /opt/fleet/last_update.json that survives the Watchtower
container swap and the post-update reboot, letting a freshly-started container know
an update just finished. Pure logic only — no FastAPI, no hardware imports.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone


def write_sentinel(
    path: str,
    state: str,
    ts: str,
    target_digest: str | None = None,
    prev_digest: str | None = None,
) -> None:
    """Persist the sentinel record to ``path``.

    ``target_digest`` (the image we are installing) and ``prev_digest`` (the image
    running when the update was triggered) are recorded when given, so the post-update
    boot can verify what actually booted. Omitting them keeps the legacy record for
    callers that don't need verification.
    """
    record: dict = {"state": state, "ts": ts}
    if target_digest:
        record["target_digest"] = target_digest
    if prev_digest:
        record["prev_digest"] = prev_digest
    with open(path, "w") as f:
        json.dump(record, f)


def classify_update(
    target_digest: str | None,
    prev_digest: str | None,
    running_digests: list[str] | None,
) -> str:
    """Pure verdict on whether an update applied, by image-digest comparison.

    ``running_digests`` is every digest the host knows the running image by. Verdict:
      "complete" — the target is among the running digests (the new image booted).
      "failed"   — the target is NOT running but the pre-update image positively is,
                   i.e. the device provably never left the old image (crash mid-update).
      "unknown"  — neither is conclusively present (host unreachable, or digest formats
                   don't line up). The caller stays optimistic, so a genuinely good
                   update is never mislabelled "failed".

    Failure is only ever declared on a POSITIVE match to the old image — never on a
    bare "differs from target" — which makes a false "Update Failed" impossible even
    if the target and running digests are recorded in different (e.g. index vs
    platform) manifest forms.
    """
    running = {d for d in (running_digests or []) if d}
    if target_digest and target_digest in running:
        return "complete"
    if prev_digest and prev_digest in running:
        return "failed"
    return "unknown"


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
      "none"          — no sentinel, unparseable, or a stale show_complete past TTL.

    The TTL is a belt-and-suspenders guard against a stale *success* popping a modal
    long after the fact — it applies ONLY to show_complete. A pending update or a
    failure must survive an arbitrarily long power-off (the headline crash scenario),
    so reboot_pending and show_failed never expire; they live until acted on/cleared.
    """
    if not record:
        return "none"
    state = record.get("state")
    if state == "reboot_pending":
        return "reboot"
    if state == "show_failed":
        return "show_failed"
    if state == "show_complete":
        age = _age_seconds(record.get("ts", ""), now)
        if age is None or age > ttl_seconds:
            return "none"
        return "show_complete"
    return "none"
