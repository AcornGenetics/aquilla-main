"""Runs the deploy-script device-identity bash harness under pytest so it stays
in CI (Phase A, Slice 3, #504).

The real verification is the bash harness, which sources only the inline
"device-identity lib" block out of deployment3_greengrass.sh and exercises the
write-once / validation / immutability logic with a shimmed chattr. This wrapper
just shells out to it and asserts it passes.
"""
import shutil
import subprocess
from pathlib import Path

import pytest

HARNESS = Path(__file__).resolve().parents[1] / "deploy" / "test_device_identity.sh"


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash not available")
def test_device_identity_deploy_harness_passes():
    result = subprocess.run(
        ["bash", str(HARNESS)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
