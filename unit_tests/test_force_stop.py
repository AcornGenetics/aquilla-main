from threading import Event

import pytest
from fastapi.testclient import TestClient

from aq_lib.thermal_engine import RunStopped, thermal_engine
from aquila_web import main as web_main


class DummyMeer:
    def __init__(self):
        self.log_called = False
        self.output_enabled = None
        self.setpoint = None

    def log(self, endtime=None, logfile=None):
        self.log_called = True

    def change_setpoint(self, setpoint):
        self.setpoint = setpoint

    def output_stage_enable(self, value):
        self.output_enabled = value


def _reset_web_state(client):
    client.post("/stop/reset")
    client.post("/run_status/reset")
    client.post("/exit/reset")
    client.post("/run/complete/ack/reset")


def test_thermal_engine_stops_with_event():
    stop_event = Event()
    stop_event.set()
    with pytest.raises(RunStopped):
        thermal_engine(
            [("hold", 1, 25.0, 30.0, 1.0, 1.0)],
            DummyMeer(),
            lambda *_: None,
            None,
            stop_event,
        )


def test_thermal_engine_runs_without_stop():
    stop_event = Event()
    meer = DummyMeer()
    thermal_engine(
        [("hold", 1, 25.0, 30.0, 1.0, 1.0)],
        meer,
        lambda *_: None,
        None,
        stop_event,
    )
    assert meer.log_called is True


def test_stop_request_sets_and_resets():
    client = TestClient(web_main.app)
    _reset_web_state(client)

    response = client.post("/button/stop")
    assert response.status_code == 200

    status = client.get("/button_status").json()
    assert status["stop_requested"] is True

    client.post("/stop/reset")
    status = client.get("/button_status").json()
    assert status["stop_requested"] is False


def test_run_clears_stop_request():
    client = TestClient(web_main.app)
    _reset_web_state(client)

    client.post("/button/stop")
    status = client.get("/button_status").json()
    assert status["stop_requested"] is True

    client.post("/button/run")
    status = client.get("/button_status").json()
    assert status["stop_requested"] is False
