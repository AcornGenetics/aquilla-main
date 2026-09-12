"""
Unit tests for the run-provenance resolver used by the run paths (issue #457).

A Run records the canonical content hash of the Profile it ran. The hardware
path (state_run_assay, 1b) hashes the doc it loads directly; the simulate path
only has the selected profile *reference*, so it resolves the profile to its
bytes via ``_profile_sha256_for`` and hashes them. This proves the recipe
recorded for a run is the exact bytes of the profile that was selected —
including Managed Profiles delivered into ``managed/``.
"""
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

for _hw in ("serial", "serial.tools", "serial.tools.list_ports"):
    sys.modules.setdefault(_hw, MagicMock())
sys.modules.setdefault("aq_lib.config_module", MagicMock())

from aq_lib.profile_hash import canonical_profile_hash  # noqa: E402

pytestmark = pytest.mark.unit


@pytest.fixture
def managed_profile():
    """A Managed Profile on disk in the resolved profile dir; cleaned up after."""
    from aquila_web import main as web_main
    content = {"title": "MgdRunProv", "post_in_gui": "True",
               "steps": [{"setpoint": 95, "duration": 1}]}
    managed = web_main.resolve_profile_dir() / "managed"
    managed.mkdir(parents=True, exist_ok=True)
    path = managed / "MgdRunProv.json"
    path.write_text(json.dumps(content))
    yield web_main, content, path
    path.unlink(missing_ok=True)


def test_resolves_managed_profile_by_id_and_hashes_bytes(managed_profile):
    web_main, content, _ = managed_profile
    expected = canonical_profile_hash(content)
    assert web_main._profile_sha256_for("managed/MgdRunProv.json") == expected


def test_resolves_managed_profile_by_name(managed_profile):
    web_main, content, _ = managed_profile
    assert web_main._profile_sha256_for("MgdRunProv") == canonical_profile_hash(content)


def test_returns_none_for_unknown_profile(managed_profile):
    web_main, _, _ = managed_profile
    assert web_main._profile_sha256_for("does_not_exist") is None
