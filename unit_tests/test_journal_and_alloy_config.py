"""Persistent journal and log-delivery verification (#354).

Config assertions rather than behaviour: these settings only take effect on a
device, but the *choices* are easy to undo by accident and each has a reason that
is not obvious from the value alone.
"""
import re
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
DEPLOY = (REPO_ROOT / "scripts" / "deploy" / "deployment2.sh").read_text()
VERIFY = (REPO_ROOT / "scripts" / "deploy" / "deployment2_verify.sh").read_text()
ALLOY = (REPO_ROOT / "scripts" / "setup_grafana_alloy_rpi.sh").read_text()
COMPOSE = yaml.safe_load((REPO_ROOT / "fleet-config" / "docker-compose.yml").read_text())


# ── Journal persistence ───────────────────────────────────────────────────────

def test_journal_is_configured_persistent():
    """Volatile storage destroys host history on every reboot — which is exactly
    when you want to read it."""
    assert "Storage=persistent" in DEPLOY


def test_journal_has_both_a_size_and_a_time_cap():
    """SystemMaxUse protects the SD card; MaxRetentionSec is what is actually
    being bought. A size cap alone lets a chatty failure evict the history an
    incident makes valuable."""
    assert "SystemMaxUse=" in DEPLOY
    assert "MaxRetentionSec=" in DEPLOY


def test_journal_batches_writes():
    """Devices boot from SD cards; fewer, larger writes suit them better."""
    assert "SyncIntervalSec=" in DEPLOY


def test_container_logging_is_still_pinned_separately():
    """journald must not become the container log path. Those go to Docker's
    json-file driver and are already capped — this change must not touch them."""
    for name in ("backend", "app", "ui"):
        logging = COMPOSE["services"][name].get("logging", {})
        assert logging.get("driver") == "json-file", f"{name} lost its json-file driver"
        assert logging["options"]["max-size"], f"{name} lost its log size cap"


# ── Alloy: assert delivery, not liveness ──────────────────────────────────────

def test_alloy_checks_assert_delivery_not_just_that_it_runs():
    """`systemctl is-active` passes while Alloy ships nothing at all — bad
    credentials, unreachable endpoint, misconfigured loki.write. Same failure
    pattern as #350."""
    assert "loki_write_sent_entries_total" in VERIFY, (
        "verification must assert log entries actually reached Grafana Cloud"
    )


def test_alloy_checks_catch_silent_dropping():
    assert "loki_write_dropped_entries_total" in VERIFY


def test_alloy_max_age_exceeds_one_day():
    """loki.source.journal only reads back max_age, so the 24h default silently
    caps what Grafana Cloud can hold after an outage — and these devices are
    routinely offline for days."""
    match = re.search(r'max_age\s*=\s*"(\d+)h', ALLOY)
    assert match, "max_age not found in the Alloy config"
    assert int(match.group(1)) > 24, (
        f"max_age is {match.group(1)}h — anything older is never shipped"
    )


def test_alloy_max_age_does_not_exceed_journal_retention():
    """Reading back further than the journal keeps is pointless.

    max_age is the number that decides whether Alloy gets everything — it only
    reads BACK that far, so anything older is never shipped no matter how long
    the journal holds it. Retention just has to be at least as long.
    """
    alloy_hours = int(re.search(r'max_age\s*=\s*"(\d+)h', ALLOY).group(1))
    retention_days = int(re.search(r"MaxRetentionSec=(\d+)d", DEPLOY).group(1))
    assert alloy_hours <= retention_days * 24


def test_backfill_window_is_seven_days():
    """Locked deliberately: the buffer only needs to cover the longest a device
    runs while unable to ship, not how long it is powered off. A larger window
    also means a returning device dumps that much into Loki in one burst."""
    alloy_hours = int(re.search(r'max_age\s*=\s*"(\d+)h', ALLOY).group(1))
    assert alloy_hours == 168, f"expected a 7-day backfill window, got {alloy_hours}h"


def test_verify_script_registers_the_new_phase():
    """A phase that exists but is not in ALL_PHASES never runs."""
    assert "test_phase_3e" in VERIFY
    assert re.search(r"ALL_PHASES=\([^)]*\b3e\b", VERIFY)
