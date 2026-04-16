"""
Unit tests for fan_class.py (Fan).

RPi.GPIO is patched at import time so no real hardware is required.
"""
import sys
import types
import importlib

import pytest

from tests.unit.conftest import MockGPIO


# ---------------------------------------------------------------------------
# Fixture: patch RPi.GPIO then import fan_class
# ---------------------------------------------------------------------------

@pytest.fixture()
def gpio():
    """A fresh MockGPIO instance per test."""
    return MockGPIO()


@pytest.fixture()
def fan_module(gpio):
    """
    Import fan_class with RPi.GPIO replaced by MockGPIO.
    Yields the module so each test can instantiate Fan.
    """
    fake_rpi_pkg = types.ModuleType("RPi")

    fake_gpio = types.ModuleType("RPi.GPIO")
    fake_gpio.BCM = MockGPIO.BCM
    fake_gpio.OUT = MockGPIO.OUT
    fake_gpio.IN = MockGPIO.IN
    fake_gpio.HIGH = MockGPIO.HIGH
    fake_gpio.LOW = MockGPIO.LOW
    fake_gpio.setmode = gpio.setmode
    fake_gpio.setwarnings = gpio.setwarnings
    fake_gpio.setup = gpio.setup
    fake_gpio.output = gpio.output
    fake_gpio.input = gpio.input
    fake_gpio.cleanup = gpio.cleanup

    with __import__("unittest.mock", fromlist=["patch"]).patch.dict(
        sys.modules,
        {
            "RPi": fake_rpi_pkg,
            "RPi.GPIO": fake_gpio,
        },
    ):
        if "fan_class" in sys.modules:
            del sys.modules["fan_class"]
        mod = importlib.import_module("fan_class")
        yield mod


@pytest.fixture()
def fan(fan_module):
    """A Fan instance ready for testing."""
    return fan_module.Fan()


# ---------------------------------------------------------------------------
# Fan.__init__
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_fan_init_sets_up_pin_as_output(fan, gpio):
    """Fan.__init__ must call GPIO.setup on FAN_PIN as OUTPUT."""
    pin = fan.FAN_PIN
    assert pin in gpio.pins, "FAN_PIN was never set up"
    assert gpio.pins[pin]["dir"] == MockGPIO.OUT


@pytest.mark.unit
def test_fan_init_sets_mode_to_bcm(gpio, fan):
    """Fan.__init__ must configure GPIO in BCM mode."""
    assert gpio.mode == MockGPIO.BCM


# ---------------------------------------------------------------------------
# Fan.set_state
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_set_state_true_sets_pin_high(fan, gpio):
    """set_state(True) must set FAN_PIN HIGH."""
    fan.set_state(True)
    assert gpio.pins[fan.FAN_PIN]["val"] == MockGPIO.HIGH


@pytest.mark.unit
def test_set_state_false_sets_pin_low(fan, gpio):
    """set_state(False) must set FAN_PIN LOW."""
    fan.set_state(False)
    assert gpio.pins[fan.FAN_PIN]["val"] == MockGPIO.LOW


@pytest.mark.unit
def test_set_state_toggle_high_then_low(fan, gpio):
    """Calling set_state(True) then set_state(False) leaves pin LOW."""
    fan.set_state(True)
    assert gpio.pins[fan.FAN_PIN]["val"] == MockGPIO.HIGH
    fan.set_state(False)
    assert gpio.pins[fan.FAN_PIN]["val"] == MockGPIO.LOW


@pytest.mark.unit
def test_set_state_toggle_low_then_high(fan, gpio):
    """Calling set_state(False) then set_state(True) leaves pin HIGH."""
    fan.set_state(False)
    assert gpio.pins[fan.FAN_PIN]["val"] == MockGPIO.LOW
    fan.set_state(True)
    assert gpio.pins[fan.FAN_PIN]["val"] == MockGPIO.HIGH


@pytest.mark.unit
def test_set_state_called_twice_same_value(fan, gpio):
    """Two consecutive set_state(True) calls leave the pin HIGH."""
    fan.set_state(True)
    fan.set_state(True)
    assert gpio.pins[fan.FAN_PIN]["val"] == MockGPIO.HIGH


@pytest.mark.unit
def test_fan_pin_number_is_17(fan):
    """Fan.FAN_PIN must be 17 per the source definition."""
    assert fan.FAN_PIN == 17
