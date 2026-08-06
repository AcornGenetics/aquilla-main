"""Unit tests for the fault states in state_config (issue #421).

A fault must route the operator to the general error page. Previously every
fault shared the "init" screen with the boot state and the Exit confirmation
flow, and the Run screen silently rewrote "init" to "ready" — so an instrument
fault was invisible to the operator. Faults now carry their own screen value so
they can be routed without disturbing boot or Exit.
"""
import json
from pathlib import Path

import pytest

# Read the shipped config directly rather than through Config(), which pulls in
# pyserial via the hardware modules. The state map is loaded verbatim, so the
# file is the honest subject of these assertions.
STATE_CONFIG_PATH = Path(__file__).parents[3] / "config_files" / "state_config.json"

# States that mean "the instrument or the software has failed".
FAULT_STATES = {
    "-1",  # instrument error
    "-2",  # invalid state requested
    "-3",  # keyboard interrupt
    "5",   # assay loop not configured to continue
}

# States that share the old "init" screen but are NOT faults and must not change.
NON_FAULT_INIT_STATES = {
    "-4",  # closing the GUI
    "-5",  # exit confirmation
    "0",   # initialising on boot
}


@pytest.fixture
def state():
    return json.loads(STATE_CONFIG_PATH.read_text())


@pytest.mark.unit
def test_fault_states_route_to_the_error_screen(state):
    for key in FAULT_STATES:
        assert state[key]["screen"] == "error", (
            f"state['{key}'] is a fault but does not route to the error screen"
        )


@pytest.mark.unit
def test_exit_and_boot_states_are_not_treated_as_faults(state):
    """Exit confirmation and boot must keep their existing behaviour."""
    for key in NON_FAULT_INIT_STATES:
        assert state[key]["screen"] == "init", (
            f"state['{key}'] is not a fault and must not route to the error screen"
        )


@pytest.mark.unit
def test_no_state_text_names_the_wrong_company(state):
    for key, entry in state.items():
        blob = f"{entry.get('title', '')} {entry.get('text', '')}".lower()
        assert "arete" not in blob, (
            f"state['{key}'] names a company other than Acorn Genetics"
        )


@pytest.mark.unit
def test_no_state_text_is_misspelled_or_developer_facing(state):
    for key, entry in state.items():
        title = entry.get("title", "")
        text = entry.get("text", "")
        blob = f"{title} {text}"
        assert "ERRROR" not in blob, f"state['{key}'] title is misspelled"
        assert ".py" not in blob, (
            f"state['{key}'] shows developer instructions to the operator"
        )
        assert "cmdline" not in blob.lower(), (
            f"state['{key}'] shows developer instructions to the operator"
        )
