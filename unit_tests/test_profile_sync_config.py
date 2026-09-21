"""Unit tests for the Profile Sync Agent's config parsing (am#488, ADR-022).

The native component receives its settings from the Greengrass recipe as env vars;
`load_config` parses + validates them. Pure function (env passed in, not read from
os.environ) so it is testable without touching global state. Marked ``unit``.
"""
import pytest

pytestmark = pytest.mark.unit

from aquila_web.profile_sync_config import load_config


def test_missing_bucket_is_a_clear_error():
    """PROFILES_BUCKET is required — the agent has nowhere to fetch from without it,
    and the failure must name the missing var, not blow up cryptically later."""
    with pytest.raises(ValueError) as exc:
        load_config({})

    assert "PROFILES_BUCKET" in str(exc.value)


def test_defaults_when_only_bucket_is_set():
    """A bare bucket is enough — managed dir and the interval backstop default."""
    cfg = load_config({"PROFILES_BUCKET": "my-bucket"})

    assert cfg.bucket == "my-bucket"
    assert cfg.managed_dir == "/opt/aquila/profiles/managed"
    assert cfg.interval_s == 300


def test_overrides_managed_dir_and_interval():
    cfg = load_config(
        {
            "PROFILES_BUCKET": "b",
            "PROFILES_MANAGED_DIR": "/tmp/m",
            "PROFILES_SYNC_INTERVAL_S": "60",
        }
    )

    assert cfg.managed_dir == "/tmp/m"
    assert cfg.interval_s == 60
