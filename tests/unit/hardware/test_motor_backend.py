"""Motion backend connects to in-container pigpiod on localhost, not the
hardcoded fleet-bridge IP (#529 / Phase C Slice 4). Guard mirrors
tests/fleet_device/test_greengrass_component.py's '172.18.0.1 must be gone'."""
from pathlib import Path

import pytest

MOTOR_SRC = Path(__file__).parents[3] / "aq_lib" / "motor_class.py"


@pytest.mark.unit
def test_motor_does_not_hardcode_the_fleet_bridge_ip():
    src = MOTOR_SRC.read_text()
    assert "172.18.0.1" not in src, (
        "motor must connect to localhost pigpiod (pigpiod runs in-container), "
        "not the hardcoded fleet-bridge IP (#529)"
    )


@pytest.mark.unit
def test_motor_connects_to_localhost_pigpiod():
    src = MOTOR_SRC.read_text()
    assert "pigpio.pi()" in src, "motor should connect to localhost pigpiod via pigpio.pi()"
