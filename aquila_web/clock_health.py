"""Is this device's clock trustworthy? (#353)

A Raspberry Pi has no battery-backed RTC. After a power loss the clock resets
and stays wrong until NTP resyncs — and `aquila_web/local_db.py:12` stamps every
outbox Event with `datetime.utcnow()`. So Events queued in that window carry
wrong timestamps and are flushed to the analytics warehouse that way. The
exposure window is the worst one: immediately after boot, while startup and
first-run Events are being written.

Two independent signals, because neither alone is sufficient:

1. systemd's NTP sync flag. Authoritative when available, but the backend runs
   in a container and only sees it if /run/systemd/timesync is bind-mounted.

2. A lower bound from the image's own baked build_time (#351). A device cannot
   legitimately be running software that has not been built yet, so a clock
   earlier than the build is definitely wrong. This needs no mounts and works
   everywhere, and it catches the dominant failure — an RTC-less Pi booting to
   the epoch or to a stale saved time.

Signal 2 is a one-sided test: it proves a clock is wrong, never that it is
right. A clock set far into the future passes it. That is why the sync flag is
preferred when present, and why `unknown` is a distinct answer from `synced`.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

# Written by systemd-timesyncd once it has successfully synchronised.
SYNC_FLAG_PATH = os.getenv("AQ_TIMESYNC_FLAG", "/run/systemd/timesync/synchronized")

# Status values
SYNCED = "synced"
UNSYNCED = "unsynced"
UNKNOWN = "unknown"


def _parse_iso(value: str | None) -> datetime | None:
    if not value or value == "unknown":
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def clock_is_before_build(build_time: str | None, now: datetime | None = None) -> bool | None:
    """True when the clock predates the running image's build — definitely wrong.

    None when it cannot be evaluated (no baked build_time, e.g. an image from
    before #351). None is not False: an unevaluable check must not read as a pass.
    """
    built = _parse_iso(build_time)
    if built is None:
        return None
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current < built


def ntp_sync_flag() -> bool | None:
    """systemd's view of whether time has been synchronised.

    None when the flag is not visible — which is the normal case in a container
    unless /run/systemd/timesync is bind-mounted. Absence of the mount is not
    evidence of an unsynced clock.
    """
    try:
        parent = Path(SYNC_FLAG_PATH).parent
        if not parent.exists():
            return None  # not mounted; no opinion
        return Path(SYNC_FLAG_PATH).exists()
    except OSError:
        return None


def clock_status(build_time: str | None = None, now: datetime | None = None) -> dict:
    """Combined verdict.

    `unsynced` means the clock is known-bad and any timestamp taken now should be
    treated as suspect. `unknown` means it could not be established — reported
    honestly rather than assumed good.
    """
    flag = ntp_sync_flag()
    before_build = clock_is_before_build(build_time, now=now)

    # A clock earlier than the running build is wrong regardless of what systemd
    # says, so this verdict wins.
    if before_build is True:
        status = UNSYNCED
        reason = "clock is earlier than this software's build time"
    elif flag is True:
        status = SYNCED
        reason = None
    elif flag is False:
        status = UNSYNCED
        reason = "NTP has not synchronised since boot"
    elif before_build is False:
        # Only the one-sided test is available and it passed: consistent, but it
        # cannot prove the clock is right.
        status = UNKNOWN
        reason = "NTP sync state unavailable; clock is at least later than the build"
    else:
        status = UNKNOWN
        reason = "NTP sync state unavailable and no baked build time to compare against"

    return {
        "clock_status": status,
        "clock_trusted": status == SYNCED,
        "clock_reason": reason,
        "ntp_synchronized": flag,
        "clock_before_build": before_build,
    }
