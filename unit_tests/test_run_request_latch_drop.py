"""
Regression test for the #333 follow-up fix.

Issue #333 made end() arm the next run whenever it saw a Run press on the
results screen. But /button/run keeps setting run_requested=True even while a
run is in progress, and nothing acks that flag until end() next polls — so a
Run press made during a run (e.g. a double-tap at run start, as seen on sn06)
survives the whole run and arms a *phantom* next run: results flash, then a new
run starts on its own.

The fix drains that latch in end() via state_requests.reset_run_request()
right after the results screen appears, so only a *fresh* press on the results
screen arms the next run.

end() itself can't be unit-imported on a dev machine (state_run_assay does
GPIO/I2C at import time — see test_run_button_double_press.py). This module
guards the piece the fix depends on: reset_run_request() must consume the
run-request edge via /run_requested/ack — which clears run_requested but
PRESERVES the selected profile (#275) — and must NOT hit /run_status/reset,
which would wipe the profile and break the single-press reuse from #333.
"""
import importlib
import sys
import types
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))


@pytest.fixture
def state_requests():
    """Import the REAL aq_lib.state_requests with hardware stubbed out, and
    fully restore module state afterward.

    aq_lib.config_module pulls in serial.tools and probes hardware in Config();
    state_requests only needs Config to *construct* at import, so we stub it.
    A sibling test (test_run_button_double_press.py) swaps the whole aq_lib
    package for a stub at collection time, so we snapshot and restore both
    sys.modules and the aq_lib package's attributes to stay order-independent.
    """
    saved_modules = dict(sys.modules)
    aq = sys.modules.get("aq_lib")
    saved_aq_attrs = dict(aq.__dict__) if aq is not None else None

    cfg = types.ModuleType("aq_lib.config_module")
    cfg.Config = lambda *a, **k: types.SimpleNamespace()
    sys.modules["aq_lib.config_module"] = cfg
    sys.modules.pop("aq_lib.state_requests", None)
    # Drop any stubbed aq_lib package (empty __path__) so the real one loads.
    if aq is not None and not getattr(aq, "__path__", None):
        sys.modules.pop("aq_lib", None)

    try:
        yield importlib.import_module("aq_lib.state_requests")
    finally:
        sys.modules.clear()
        sys.modules.update(saved_modules)
        if aq is not None and saved_aq_attrs is not None:
            aq.__dict__.clear()
            aq.__dict__.update(saved_aq_attrs)


def test_reset_run_request_acks_edge_without_wiping_profile(state_requests, monkeypatch):
    """reset_run_request() acks the run edge and preserves the profile."""
    calls = []
    monkeypatch.setattr(
        state_requests.requests,
        "post",
        lambda url, *a, **k: calls.append(url) or types.SimpleNamespace(),
    )

    state_requests.reset_run_request()

    assert len(calls) == 1, "expected exactly one POST"
    assert calls[0].endswith("/run_requested/ack")
    # Load-bearing: /run_status/reset would clear selected_profile too, breaking
    # the single-press profile reuse the #333 fix relies on.
    assert "/run_status/reset" not in calls[0]


def test_reset_run_request_swallows_backend_errors(state_requests, monkeypatch):
    """A backend that's down must not crash the end-of-run path."""
    def _boom(*a, **k):
        raise state_requests.requests.exceptions.RequestException("backend down")

    monkeypatch.setattr(state_requests.requests, "post", _boom)

    # Must not raise — end() runs this on the results screen; an exception here
    # would take down application.main()'s loop.
    state_requests.reset_run_request()
