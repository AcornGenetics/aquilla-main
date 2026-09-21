"""Config for the native Profile Sync Agent component (am#488, ADR-022).

The Greengrass recipe passes settings to the process as environment variables;
`load_config` parses and validates them into a `SyncConfig`. `env` is injected
(defaults to `os.environ`) so the parser is pure and unit-testable.
"""
import os
from dataclasses import dataclass
from typing import Mapping, Optional

DEFAULT_MANAGED_DIR = "/opt/aquila/profiles/managed"
DEFAULT_INTERVAL_S = 300  # 5-minute backstop (catches in-place S3 edits)


@dataclass(frozen=True)
class SyncConfig:
    bucket: str
    managed_dir: str
    interval_s: int


def load_config(env: Optional[Mapping[str, str]] = None) -> SyncConfig:
    """Parse the agent's settings from `env`. Raises ValueError naming the offender."""
    env = os.environ if env is None else env

    bucket = env.get("PROFILES_BUCKET")
    if not bucket:
        raise ValueError("PROFILES_BUCKET is required (the S3 bucket holding profile bodies)")

    return SyncConfig(
        bucket=bucket,
        managed_dir=env.get("PROFILES_MANAGED_DIR", DEFAULT_MANAGED_DIR),
        interval_s=int(env.get("PROFILES_SYNC_INTERVAL_S", DEFAULT_INTERVAL_S)),
    )
