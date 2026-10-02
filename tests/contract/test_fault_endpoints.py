"""
Contract tests for the dismissable thermal-controller fault message (#519).

The fault is orthogonal to the screen state machine: POST /fault/ raises it,
GET /fault/ reports it, and POST /fault/dismiss (the operator's X) clears it.
"""
import pytest

FAULT = {
    "title": "THERMAL CONTROLLER FAULT",
    "text": "Power cycle the device and try again. If the error persists, contact Acorn Genetics.",
    "screen": "init",
}


@pytest.mark.contract
def test_set_fault_then_get_returns_it(client):
    client.post("/fault/dismiss")  # clean slate
    try:
        resp = client.post("/fault/", json=FAULT)
        assert resp.status_code == 200
        fault = client.get("/fault/").json()["fault"]
        assert fault["title"] == FAULT["title"]
        assert fault["text"] == FAULT["text"]
    finally:
        client.post("/fault/dismiss")


@pytest.mark.contract
def test_dismiss_clears_fault(client):
    client.post("/fault/", json=FAULT)
    client.post("/fault/dismiss")
    assert client.get("/fault/").json()["fault"] is None


@pytest.mark.contract
def test_no_fault_by_default(client):
    client.post("/fault/dismiss")
    assert client.get("/fault/").json()["fault"] is None
