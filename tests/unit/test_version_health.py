"""
Unit tests for the matched-pair Container Health logic (am#360).

A Sentri runs an api container and a ui container. They must come from the SAME
build — a mismatch (api updated, ui stale, or vice-versa) is the sn04 failure
mode and must block runs. These are pure functions over the two running build
SHAs, so they carry no Greengrass/IPC dependency.

Run with:
    pytest tests/unit/test_version_health.py -v
"""
import pytest

pytestmark = pytest.mark.unit

from aquila_web.version_health import (
    build_shadow_report,
    is_matched_pair,
    runs_allowed,
    should_defer_update,
    update_banner,
    update_outcome,
)


class TestUpdateOutcome:
    """Did the last update apply, or did Greengrass roll it back? (am#394)

    The device records the git_sha it was running just before it let an update
    apply. On the next boot (or a post-update event) it compares that to the sha
    it's actually running now — the ground truth of what Greengrass left it on.
    """

    def test_rolled_back_when_still_on_the_pre_update_build(self):
        # Recorded "old" before applying, but we're STILL "old" — Greengrass
        # reverted us. The last update failed.
        assert update_outcome("old_sha", "old_sha") == "rolled_back"

    def test_none_when_no_update_was_in_flight(self):
        # No pre-apply sha recorded ⇒ this is a normal boot, not a post-update one.
        # Must never surface a banner.
        assert update_outcome(None, "any_sha") == "none"

    def test_succeeded_when_now_on_a_different_build(self):
        # Recorded "old", now running "new" — the switch took. No banner.
        assert update_outcome("old_sha", "new_sha") == "succeeded"

    def test_none_when_current_build_is_unknown(self):
        # We recorded a pre-apply sha but can't read our own build now — don't
        # guess a failure (fail safe: no banner).
        assert update_outcome("old_sha", None) == "none"


@pytest.mark.parametrize(
    "api_sha, ui_sha, expected",
    [
        ("abc123", "abc123", True),   # same build → matched
        ("abc123", "def456", False),  # different builds → mismatch (sn04)
    ],
)
def test_is_matched_pair(api_sha, ui_sha, expected):
    assert is_matched_pair(api_sha, ui_sha) is expected


@pytest.mark.parametrize(
    "api_sha, ui_sha",
    [
        (None, None),      # neither reported → unknown, must block
        ("abc123", None),  # ui not reported yet
        (None, "abc123"),  # api not reported yet
        ("", ""),          # empty is not a real build id
    ],
)
def test_missing_sha_is_not_a_matched_pair(api_sha, ui_sha):
    # Unknown identity must never read as "matched" — fail safe, block runs.
    assert is_matched_pair(api_sha, ui_sha) is False


def test_shadow_report_carries_shas_and_matched_health():
    report = build_shadow_report("abc123", "abc123")
    assert report["images"] == {"api": "abc123", "ui": "abc123"}
    assert report["container_health"] == "matched"


def test_shadow_report_flags_mismatch():
    report = build_shadow_report("abc123", "def456")
    assert report["container_health"] == "mismatched"


def test_failed_update_shows_non_blocking_banner():
    banner = update_banner(last_update_failed=True)
    assert banner is not None
    assert banner["blocking"] is False  # informational — the operator can still run
    assert "previous version" in banner["message"].lower()


def test_no_banner_when_update_healthy():
    assert update_banner(last_update_failed=False) is None


@pytest.mark.parametrize(
    "operator_approved, expected_defer",
    [
        (False, True),   # not yet approved → defer (hold at the badge)
        (True, False),   # approved → apply; run state is not a factor (am#382 follow-up)
    ],
)
def test_should_defer_update(operator_approved, expected_defer):
    assert should_defer_update(operator_approved) is expected_defer


@pytest.mark.parametrize(
    "api_sha, ui_sha, allowed",
    [
        ("abc123", "abc123", True),   # matched → allow (incl. a matched older build)
        ("abc123", "def456", False),  # KNOWN mismatch → block (sn04)
        (None, "abc123", True),       # unknown identity → allow, never brick
        ("abc123", None, True),
        (None, None, True),
    ],
)
def test_runs_allowed(api_sha, ui_sha, allowed):
    assert runs_allowed(api_sha, ui_sha) is allowed
