"""
D5 — STATE_DIR parameterization (rebrand #187, ADR-015).

The `/opt/aquila` host state directory is a deliberate carve-out (kept), but to
make a future migration to `/opt/sentri` a one-line env change rather than a
compose rewrite, the device bind-mount HOST paths are parameterized behind
`${STATE_DIR:-/opt/aquila}`. The default preserves current behavior exactly.
"""
import re
from pathlib import Path

FLEET_COMPOSE = Path("fleet-config/docker-compose.yml")
HOST_SIDE_RE = re.compile(r"^\s*-\s*([^:\s]+):", re.MULTILINE)
STATE_DIR_PREFIX = "${STATE_DIR:-/opt/aquila}"


def test_device_state_binds_use_state_dir():
    text = FLEET_COMPOSE.read_text()
    offenders = [
        host for host in HOST_SIDE_RE.findall(text)
        if host.startswith("/opt/aquila")
    ]
    assert not offenders, (
        "device state bind-mount host path(s) still hardcode /opt/aquila instead "
        f"of {STATE_DIR_PREFIX}:\n" + "\n".join(f"  - {o}" for o in offenders)
    )


def test_state_dir_default_preserves_opt_aquila():
    text = FLEET_COMPOSE.read_text()
    assert STATE_DIR_PREFIX in text, (
        "expected the parameterized default to preserve /opt/aquila"
    )
