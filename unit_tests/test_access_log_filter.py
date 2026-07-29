"""Access-log noise suppression (#354).

Measured on sn08: aquila-backend produced 19 MB of container log in two days —
48x the next container — almost entirely `GET /button_status/ 200 OK` from the
kiosk's poll loop. That buries update decisions, sync results and errors, and
once container logs ship to Grafana Cloud it is paid for twice.

The rule under test: drop SUCCESSFUL polls of known-noisy endpoints, keep
everything else. A failing poll must still log, or the access log stops doing its
one job.
"""
import logging
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from aquila_web.main import _QuietPollFilter, _QUIET_ACCESS_PATHS  # noqa: E402


def _record(path, status, method="GET"):
    """Build a record shaped the way uvicorn.access emits them."""
    rec = logging.LogRecord("uvicorn.access", logging.INFO, __file__, 0, "%s", None, None)
    rec.args = ("172.18.0.5:55588", method, path, "1.1", status)
    return rec


@pytest.fixture
def filt():
    return _QuietPollFilter()


# ── The noise ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("path", sorted(_QUIET_ACCESS_PATHS))
def test_successful_polls_are_dropped(filt, path):
    assert filt.filter(_record(path, 200)) is False


def test_query_strings_do_not_defeat_the_match(filt):
    assert filt.filter(_record("/results?limit=5", 200)) is False


# ── What must survive ─────────────────────────────────────────────────────────

def test_a_failing_poll_still_logs(filt):
    """The endpoint going wrong is exactly what an access log is for."""
    assert filt.filter(_record("/button_status/", 500)) is True
    assert filt.filter(_record("/health", 503)) is True


def test_unrelated_endpoints_still_log(filt):
    for path in ("/update/apply", "/profiles", "/button/run", "/identity"):
        assert filt.filter(_record(path, 200)) is True, path


def test_non_get_requests_still_log(filt):
    """A POST to a polled path is an action, not a poll."""
    assert filt.filter(_record("/results/clear", 200, method="POST")) is True


# ── Never lose a line to a shape it did not expect ────────────────────────────

def test_records_without_uvicorn_args_are_kept(filt):
    rec = logging.LogRecord("uvicorn.access", logging.INFO, __file__, 0, "boom", None, None)
    assert filt.filter(rec) is True


def test_short_or_odd_args_are_kept(filt):
    rec = logging.LogRecord("uvicorn.access", logging.INFO, __file__, 0, "%s", ("a", "b"), None)
    assert filt.filter(rec) is True


def test_unparseable_status_is_kept(filt):
    assert filt.filter(_record("/health", "not-a-status")) is True


def test_non_string_path_is_kept(filt):
    rec = logging.LogRecord("uvicorn.access", logging.INFO, __file__, 0, "%s", None, None)
    rec.args = ("addr", "GET", None, "1.1", 200)
    assert filt.filter(rec) is True


def test_application_logging_is_untouched(filt):
    """Only uvicorn.access is filtered — logger.info/error must never be dropped."""
    rec = logging.LogRecord("aquila_web.main", logging.ERROR, __file__, 0,
                            "update failed", None, None)
    assert filt.filter(rec) is True
