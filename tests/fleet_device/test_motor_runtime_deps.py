"""Guards for the motor runtime dependency chain, after the 0.1.69 bring-up crash.

aq_lib.motor_class imports pigpio at module load and connects with pigpio.pi().
For the containerised app that requires two things the 15-well merge missed:
  1. the pigpio *client* must be installed in the api image (it crashed with
     'ModuleNotFoundError: No module named pigpio'), and
  2. pigpio.pi() must reach pigpiod, which runs on the HOST — the bridge app
     container can't use its own localhost, so it targets PIGPIO_ADDR.
"""
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).parents[2]


@pytest.mark.unit
def test_motor_class_imports_pigpio_at_module_load():
    # The premise these guards defend: a missing pigpio crashes the app at import.
    assert "import pigpio" in (ROOT / "aq_lib" / "motor_class.py").read_text()


@pytest.mark.unit
def test_pigpio_client_is_in_the_backend_image_requirements():
    reqs = [l.split("#")[0].strip()
            for l in (ROOT / "requirements-backend.txt").read_text().splitlines()]
    assert "pigpio" in reqs, (
        "aq_lib.motor_class imports pigpio; it must be in requirements-backend.txt "
        "or the app container crashes at import (the 0.1.69 bring-up failure)"
    )


@pytest.mark.unit
def test_app_service_points_pigpio_at_the_host_daemon():
    svc = yaml.safe_load((ROOT / "fleet-config" / "greengrass-compose.yaml").read_text())
    env = svc["services"]["app"]["environment"]
    assert any(str(e) == "PIGPIO_ADDR=host.docker.internal" for e in env), (
        "pigpiod runs on the host; the bridge app container reaches it via "
        "PIGPIO_ADDR=host.docker.internal, not its own localhost"
    )
