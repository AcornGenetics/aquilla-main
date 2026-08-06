"""Unit tests for the boot splash's failure path (issue #421).

The splash is deployed as a standalone local file and loads before the backend
is up, so it cannot navigate to /error when the backend is the thing that is
broken — it has to carry the wording itself. Previously it retried forever on
"Taking longer than expected…", leaving the operator with no indication that
anything was actually wrong.
"""
from pathlib import Path

import pytest

SPLASH = Path(__file__).parents[2] / "aquila_web" / "static" / "splash.html"


@pytest.fixture
def splash():
    return SPLASH.read_text(encoding="utf-8")


@pytest.mark.unit
def test_splash_escalates_to_the_general_error_wording(splash):
    assert "Something went wrong" in splash
    assert "Please try again or restart the device" in splash
    assert "If the issue continues, contact Acorn Genetics for support." in splash


@pytest.mark.unit
def test_splash_no_longer_waits_indefinitely(splash):
    assert "Taking longer than expected" not in splash


@pytest.mark.unit
def test_splash_stays_self_contained(splash):
    """It runs from disk before the app exists, so it must not pull in app assets."""
    assert "styles.css" not in splash
