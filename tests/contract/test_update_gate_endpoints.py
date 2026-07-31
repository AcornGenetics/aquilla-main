"""
Contract test: the operator update-gate endpoints (am#382).

GET /update/gate reports the pre-staged-update state; POST /update/approve is the
"Update" button that releases the deferred switch. Uses the shared UpdateGate the
Phase-2 Greengrass IPC agent also reads.
"""
import pytest

from aquila_web import update_gate

pytestmark = pytest.mark.contract


@pytest.fixture(autouse=True)
def _fresh_gate():
    update_gate.GATE = update_gate.UpdateGate()
    yield
    update_gate.GATE = update_gate.UpdateGate()


def test_approve_button_records_operator_approval(client):
    # Greengrass offers an update (what the IPC agent will do on the device).
    update_gate.GATE.mark_pending("0.1.20")

    assert client.get("/update/gate").json()["approved"] is False

    client.post("/update/approve")  # operator taps "Update"

    body = client.get("/update/gate").json()
    assert body["approved"] is True
    assert body["pending"] is True
    assert body["target_version"] == "0.1.20"
