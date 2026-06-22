"""
Hardware mock fixtures for all Layer 1 unit tests.
No real hardware, no network — runs on any machine.
"""
import io
from threading import Event
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# MeerStetter mock
# ---------------------------------------------------------------------------

class DummyMeer:
    """Full mock of MeerStetter thermal controller."""

    def __init__(self):
        self.setpoints = []
        self.output_stages = []
        self.log_calls = []
        self.kp_values = []
        self.ti_values = []
        self.td_values = []

    def change_setpoint(self, temp):
        self.setpoints.append(temp)

    def output_stage_enable(self, value):
        self.output_stages.append(value)

    def log(self, endtime=None, logfile=None, stop_event=None):
        self.log_calls.append({"endtime": endtime})
        # Respect stop_event so tests that set it don't hang
        if stop_event and stop_event.is_set():
            from sentri_lib.thermal_engine import RunStopped
            raise RunStopped("stopped in mock")

    def setKp(self, value):
        self.kp_values.append(value)

    def setTi(self, value):
        self.ti_values.append(value)

    def setTd(self, value):
        self.td_values.append(value)

    def get_parid_float(self, parid):
        return 25.0

    def get_parid_long(self, parid):
        return 0


# ---------------------------------------------------------------------------
# GPIO mock
# ---------------------------------------------------------------------------

class MockGPIO:
    """Mock of RPi.GPIO — tracks pin states."""

    BCM = "BCM"
    BOARD = "BOARD"
    OUT = "OUT"
    IN = "IN"
    HIGH = 1
    LOW = 0
    PUD_UP = "PUD_UP"
    PUD_DOWN = "PUD_DOWN"

    def __init__(self):
        self.pins = {}
        self.mode = None
        self._home_pins = set()  # pins that simulate a home flag

    def setmode(self, mode):
        self.mode = mode

    def setwarnings(self, value):
        pass

    def setup(self, pin, direction, pull_up_down=None, initial=None):
        self.pins[pin] = {"dir": direction, "val": initial if initial is not None else 0}

    def output(self, pin, value):
        if pin not in self.pins:
            self.pins[pin] = {"dir": self.OUT, "val": value}
        self.pins[pin]["val"] = value

    def input(self, pin):
        return self.pins.get(pin, {}).get("val", 0)

    def cleanup(self):
        self.pins.clear()

    def simulate_home_flag(self, pin, value=1):
        """Helper: set a pin HIGH to simulate home flag detection."""
        if pin not in self.pins:
            self.pins[pin] = {"dir": self.IN, "val": value}
        else:
            self.pins[pin]["val"] = value


# ---------------------------------------------------------------------------
# SPI mock
# ---------------------------------------------------------------------------

class MockSPI:
    """Mock of spidev.SpiDev — records xfer2 calls."""

    def __init__(self, return_bytes=None):
        self.xfer2_calls = []
        self._return_bytes = return_bytes or [0x00, 0x00, 0x00]
        self.max_speed_hz = 0
        self.mode = 0
        self.bits_per_word = 8

    def open(self, bus, device):
        pass

    def close(self):
        pass

    def xfer2(self, data):
        self.xfer2_calls.append(list(data))
        return self._return_bytes[: len(data)]

    def writebytes(self, data):
        self.xfer2_calls.append(list(data))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def dummy_meer():
    return DummyMeer()


@pytest.fixture
def mock_gpio():
    return MockGPIO()


@pytest.fixture
def mock_spi():
    return MockSPI()


@pytest.fixture
def stop_event():
    return Event()


@pytest.fixture
def logfile():
    return io.StringIO()
