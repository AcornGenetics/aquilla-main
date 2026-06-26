"""
Unit tests for the version-computation helper used by the cut-version
release workflow. Pure logic only — no git / network I/O.
"""
import pytest

from aq_lib.version_tool import (
    resolve_next,
    sorts_below,
    validate_ring_assignment,
)


def test_blank_custom_bumps_last_segment():
    """With no custom version, the next version increments the last segment."""
    assert resolve_next("1.2.6.6", None, existing=set()) == "1.2.6.7"


def test_bump_is_length_agnostic():
    """The last segment is bumped regardless of how many segments exist."""
    assert resolve_next("1.2.6", None, existing=set()) == "1.2.7"
    assert resolve_next("1.2.5.5.4", None, existing=set()) == "1.2.5.5.5"


def test_custom_version_is_used_verbatim():
    """A valid, novel custom version overrides the auto-bump and is used as-is."""
    assert resolve_next("1.2.6.6", "2.0.0", existing=set()) == "2.0.0"


def test_custom_version_that_exists_is_rejected():
    """Versions are write-once: a custom value already in use is rejected."""
    with pytest.raises(ValueError):
        resolve_next("1.2.6.6", "1.2.6.5", existing={"1.2.6.5"})


@pytest.mark.parametrize("bad", ["1.2.x", "v1.2", "1..2", "1.2."])
def test_malformed_custom_version_is_rejected(bad):
    """A custom version must be dot-separated integers."""
    with pytest.raises(ValueError):
        resolve_next("1.2.6.6", bad, existing=set())


def test_sorts_below_detects_a_lower_custom_version():
    """sorts_below flags a candidate that orders earlier than the latest
    (a likely typo) while accepting a higher one."""
    assert sorts_below("1.2.5.9", "1.2.6.6") is True
    assert sorts_below("1.2.6.7", "1.2.6.6") is False


def test_ring_assignment_accepts_existing_version_and_valid_ring():
    """A built version may be assigned to a valid ring."""
    validate_ring_assignment("1.2.6.7", "prod", existing_versions={"1.2.6.7"})


def test_ring_assignment_rejects_version_without_image():
    """A version with no built image cannot be assigned to a ring."""
    with pytest.raises(ValueError):
        validate_ring_assignment("1.2.6.7", "prod", existing_versions=set())


@pytest.mark.parametrize("unversioned", ["8b2ae45", "latest"])
def test_ring_assignment_rejects_unversioned_input(unversioned):
    """A raw SHA or 'latest' is not a version, so it can never be assigned —
    the membership gate covers it (such inputs are never in existing_versions)."""
    with pytest.raises(ValueError):
        validate_ring_assignment(unversioned, "prod", existing_versions={"1.2.6.7"})


def test_ring_assignment_rejects_unknown_ring():
    """Only dev/pilot/prod are valid rings."""
    with pytest.raises(ValueError):
        validate_ring_assignment("1.2.6.7", "staging", existing_versions={"1.2.6.7"})
